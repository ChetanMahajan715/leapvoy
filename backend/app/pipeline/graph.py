"""LangGraph pipeline for one post: prefilter → match → extract → fit.

Each node saves its result on the post/job rows before the next runs, and the graph starts at the post's
saved stage: so a crash or rate-limit resumes where it stopped and never pays for an LLM stage twice.
"""

import json
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse
from typing import TypedDict

import structlog
from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.accounts.profile import get_profile
from app.core.config import get_settings
from app import notify
from app.db.models import Job, Post
from app.llm import prompts
from app.llm.router import AIUnreachable, RateLimited, structured
from app.llm.schemas import ExtractedPost, FitCheck, JobPost
from app.pipeline import store
from app.pipeline.prefilter import prefilter
from app.pipeline.resume import active_resume, match_score
from app.pipeline.rules import apply_rules, title_is_unrelated
from app.pipeline.sections import excerpt, split_jobs

log = structlog.get_logger()
SessionMaker = async_sessionmaker[AsyncSession]
MATCH_TEXT_LIMIT = 2000  # bge reads ~512 tokens; the start of a post holds company/role/skills


def ground_links(links: list[str], post_links: list[str]) -> list[str]:
    """Keep only links that are in the post. A link the LLM shortened (e.g. dropped '?usp=header')
    is replaced by the post's real one; a bare domain is never enough to match."""
    out: list[str] = []
    for raw in links:
        link = raw.strip().rstrip(".,;:!?)]}>'\"")
        link = link if link.lower().startswith("http") else f"https://{link}"
        real = link if link in post_links else None
        if real is None and urlparse(link).path.strip("/"):
            real = next((p for p in post_links if p.startswith(link) or link.startswith(p)), None)
        if real and real not in out:
            out.append(real)
    return out


SKIP_UNRELATED = FitCheck(  # saved without an AI call for titles like "Business Analyst", "QA Intern"
    score=10, rows=[], verdict="SKIP", role_family="unrelated", min_years_required=None, batch_eligible=True,
    matched_skills=[], gaps=[], flags=["not a target role (title), skipped without AI"],
)


class NoResume(Exception):
    """User hasn't added a resume yet: posts wait at stage 'new' (not counted as a failure)."""


class State(TypedDict):
    post_id: int
    stage: str


def build(sm: SessionMaker):
    async def prefilter_node(state: State) -> State:
        async with sm() as s:
            post = await s.get(Post, state["post_id"])
            r = prefilter(post.text)
            if not r.keep:
                await store.update_post(s, post.id, stage="skipped", skip_reason=r.reason, text_hash=r.text_hash)
                return {**state, "stage": "skipped"}
            if await store.is_repost(s, post, r.text_hash):
                await store.update_post(s, post.id, stage="skipped", skip_reason="duplicate", text_hash=r.text_hash)
                return {**state, "stage": "skipped"}
            await store.update_post(s, post.id, text_hash=r.text_hash, emails=r.emails, links=r.links)
        return {**state, "stage": "prefiltered"}

    async def match_node(state: State) -> State:
        async with sm() as s:
            post = await s.get(Post, state["post_id"])
            # a post listing many jobs: each job is matched on its own text (the start of a long post would hide the rest)
            blocks = [b[:MATCH_TEXT_LIMIT] for b in split_jobs(post.text)]
            score = await match_score(s, post.user_id, [post.text[:MATCH_TEXT_LIMIT], *blocks])
            if score is None:
                raise NoResume
            ok = score >= get_settings().match_threshold
            await store.update_post(
                s, post.id, match_score=score, stage="matched" if ok else "skipped", skip_reason=None if ok else "low_match"
            )
        return {**state, "stage": "matched" if ok else "skipped"}

    async def extract_node(state: State) -> State:
        async with sm() as s:
            post = await s.get(Post, state["post_id"])

            async def read(text: str) -> list[JobPost]:
                msgs = [{"role": "system", "content": prompts.load("extract")}, {"role": "user", "content": text}]
                return (await structured("small", msgs, ExtractedPost)).jobs

            found = await read(post.text)
            blocks = split_jobs(post.text)
            if len(found) < len(blocks):  # the AI missed some jobs of a long list: read each job's block on its own
                found = [j for b in blocks for j in await read(b)]
            allowed = set(post.emails)  # the LLM may only use addresses/links that are really in the post
            jobs: list[JobPost] = []
            single = len(found) == 1
            for j in found:
                emails = [e for e in dict.fromkeys(e.strip().lower() for e in j.hr_emails) if e in allowed]
                links = ground_links(j.apply_links, post.links)
                if single and not j.hr_emails and not j.apply_links:  # the AI forgot how to apply (gave nothing,
                    # not an invented address, which stays dropped); the post itself says it.
                    # Seen live 1 Oct: a backup model dropped Google Form links.
                    emails = list(post.emails)
                    links = [] if emails else list(post.links)
                if emails or links:  # a job you can't apply to (no email, no link) is dropped
                    jobs.append(j.model_copy(update={"hr_emails": emails, "apply_links": links}))
            if not jobs:
                await store.update_post(s, post.id, stage="skipped", skip_reason="no_valid_job")
                return {**state, "stage": "skipped"}
            await store.replace_jobs(s, post, jobs)
        return {**state, "stage": "extracted"}

    async def fit_node(state: State) -> State:
        async with sm() as s:
            post = await s.get(Post, state["post_id"])
            resume = await active_resume(s, post.user_id)
            if resume is None:
                raise NoResume
            system = prompts.load("fit").format(
                profile=json.dumps(await get_profile(s, post.user_id), ensure_ascii=False), resume=resume.text
            )
            siblings = (await s.execute(select(Job).where(Job.post_id == post.id).order_by(Job.idx))).scalars().all()
            names = [(j.company, j.role) for j in siblings]
            for job in await store.unscored_jobs(s, post.id):  # saved per job → resumes mid-post
                if title_is_unrelated(job.role):  # the rules would force SKIP anyway → save ~3k tokens
                    await store.save_fit(s, job.id, SKIP_UNRELATED, resume.id)
                    continue
                own = excerpt(post.text, names, job.idx, job.hr_emails, job.apply_links)  # only this job's part
                job_json = json.dumps(
                    {k: getattr(job, k) for k in ("company", "role", "experience", "location", "work_mode",
                                                  "must_have_skills", "salary", "apply_instructions")},
                    ensure_ascii=False,
                )
                fit = await structured(
                    "large",
                    [{"role": "system", "content": system},
                     {"role": "user", "content": f"Job:\n{job_json}\n\nOriginal post:\n{own}"}],
                    FitCheck,
                )
                await store.save_fit(s, job.id, apply_rules(fit, job.role), resume.id)  # user's rules decide
            await store.update_post(s, post.id, stage="scored", skip_reason=None)
            await s.refresh(post)
            jobs = (await s.execute(select(Job).where(Job.post_id == post.id))).scalars().all()
            await notify.job_alerts(s, post, jobs, datetime.now(UTC))  # good fits → inbox + phone
            await s.commit()
        return {**state, "stage": "scored"}

    def after(next_node: str):
        return lambda state: END if state["stage"] == "skipped" else next_node

    def start(state: State) -> str:
        return {"new": "prefilter", "matched": "extract", "extracted": "fit"}.get(state["stage"], END)

    g = StateGraph(State)
    g.add_node("prefilter", prefilter_node)
    g.add_node("match", match_node)
    g.add_node("extract", extract_node)
    g.add_node("fit", fit_node)
    g.add_conditional_edges(START, start)
    g.add_conditional_edges("prefilter", after("match"))
    g.add_conditional_edges("match", after("extract"))
    g.add_conditional_edges("extract", after("fit"))
    g.add_edge("fit", END)
    return g.compile()


async def run_post(sm: SessionMaker, post_id: int) -> str:
    """Advance one post as far as possible. Returns its stage afterwards ("busy": another process has it)."""
    async with sm() as lock:  # chat's "check Telegram" and the pipeline worker can reach the same post at once
        if not await lock.scalar(select(func.pg_try_advisory_lock(post_id))):
            return "busy"
        try:
            return await _run_post(sm, post_id)
        finally:
            await lock.execute(select(func.pg_advisory_unlock(post_id)))


async def _run_post(sm: SessionMaker, post_id: int) -> str:
    async with sm() as s:
        post = await s.get(Post, post_id)
        stage = post.stage
    try:
        out = await build(sm).ainvoke({"post_id": post_id, "stage": stage})
        return out["stage"]
    except NoResume:
        return stage
    except RateLimited:  # free-tier minute limit: stages done so far are saved; next round continues
        return "rate_limited"
    except AIUnreachable:  # no internet / providers down: not this post's fault, never counted as a failed try
        log.warning("pipeline.ai_unreachable", post_id=post_id)
        return "unreachable"
    except Exception as e:  # noqa: BLE001, any failure (LLMUnavailable, DB, bug) is recorded and retried
        log.warning("pipeline.post_failed", post_id=post_id, error=repr(e)[:300])
        async with sm() as s:
            await store.record_failure(s, await s.get(Post, post_id), type(e).__name__)
        return "failed"


async def run_user(
    sm: SessionMaker, user_id: uuid.UUID, limit: int = 10, since: datetime | None = None, until: datetime | None = None
) -> dict[str, int]:
    async with sm() as s:
        ids = await store.next_posts(s, user_id, limit, since, until)
    counts: dict[str, int] = {}
    for post_id in ids:
        stage = await run_post(sm, post_id)
        counts[stage] = counts.get(stage, 0) + 1
    return counts
