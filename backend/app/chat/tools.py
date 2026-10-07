"""What the chat assistant can do. Each tool returns text for the AI + an optional card for the app.

Anything that sends, cancels or moves an email only creates a PendingAction (a Confirm card);
it runs when the user taps Confirm (app/chat/actions.py). The AI can never send by itself.
"""

import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.models import Channel, Draft, Job, Memory, PendingAction, Post, Send
from app.mailer import drafts, outbox, senders
from app.llm import usage
from app.mailer.when import parse_when
from app.pipeline import graph, posts as post_info, report
from app.pipeline import store as pipeline_store
from app.telegram import reader
from app.telegram import store as tg_store
from app.pipeline.prefilter import prefilter

TEST_NOTE = " · TEST MODE: goes to your own inbox"
FETCH_LIMIT = 60  # posts looked at per "check Telegram now"
FETCH_SECONDS = 40  # then answer; the rest continue in the background pipeline (chat never hangs on a backlog)


@dataclass(frozen=True)
class Context:
    now: datetime
    incognito: bool
    last_user_message: str


@dataclass(frozen=True)
class ToolResult:
    text: str
    card: dict[str, Any] | None = None


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required or []},
    }}


_WHEN = {"type": "string", "description": 'India time, e.g. "now", "tomorrow 10am", "monday 10am", "2026-10-01 11:15"'}
TOOLS = [
    _fn("list_jobs", "Jobs of one day that fit the user's resume (best first), shown as job cards.",
        {"date": {"type": "string", "description": '"today", "yesterday" or YYYY-MM-DD (India time)'}}),
    _fn("list_posts", "EVERY job posted on one day, fit or not (a Telegram post can list many jobs; each is its own "
        "card with its own score, newest first). Use when the user asks for all jobs / all posts / everything posted.",
        {"date": {"type": "string", "description": '"today", "yesterday" or YYYY-MM-DD (India time)'}}),
    _fn("search_posts", "Find saved Telegram posts mentioning a company / role / words, INCLUDING ones Leapvoy skipped, "
        "and say what happened to each (matched job, or why it was skipped). Use when the user asks whether a "
        "specific job or company is there.",
        {"query": {"type": "string", "description": 'e.g. "blinkit program manager"'},
         "days": {"type": "integer", "description": "how far back, default 7"}}, ["query"]),
    _fn("check_telegram", "Read Telegram right now for new posts, process that day's posts and show its jobs. Use when "
        "the user asks to fetch / check / refresh jobs, or list_jobs says no posts were read yet. Takes a minute or two.",
        {"date": {"type": "string", "description": '"today", "yesterday" or YYYY-MM-DD (India time)'}}),
    _fn("analyze_pasted_job", "The user's last message is a pasted job post, or the text of an attached JD / document / "
        "screenshot: find the job(s) in it and check the fit against the resume. Shown as job cards. "
        "Then write_email can draft the email for it.", {}),
    _fn("write_email", "Show the application email for one job, writing it if missing. rewrite=true only when the user asks to change or redo it.",
        {"job_id": {"type": "integer"}, "rewrite": {"type": "boolean"}}, ["job_id"]),
    _fn("schedule_email", "Propose sending a job's email now or at a time. The user must tap Confirm.",
        {"job_id": {"type": "integer"}, "when": _WHEN}, ["job_id"]),
    _fn("list_scheduled", "Emails waiting to be sent, optionally for one day.",
        {"date": {"type": "string", "description": '"today", "tomorrow"… or YYYY-MM-DD'}}),
    _fn("cancel_email", "Propose cancelling a scheduled email. The user must tap Confirm.",
        {"send_id": {"type": "integer"}}, ["send_id"]),
    _fn("reschedule_email", "Propose moving a scheduled email to another time. The user must tap Confirm.",
        {"send_id": {"type": "integer"}, "when": _WHEN}, ["send_id", "when"]),
    _fn("stats", "Counts for the last N days: posts read, jobs matched, emails sent, replies.",
        {"days": {"type": "integer", "description": "default 7"}}),
    _fn("remember", "Save a lasting preference the user states (e.g. 'prefer sending at 10 AM', 'skip Bangalore').",
        {"fact": {"type": "string"}}, ["fact"]),
]


def _when_text(t: datetime) -> str:
    return f"{t.astimezone(report.IST):%a %d %b, %I:%M %p} IST"


async def _job(s: AsyncSession, user_id: uuid.UUID, job_id: int) -> Job | None:
    return (await s.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))).scalar_one_or_none()


async def _propose(s: AsyncSession, user_id: uuid.UUID, kind: str, payload: dict, summary: str) -> ToolResult:
    action = PendingAction(user_id=user_id, kind=kind, payload=payload, summary=summary)
    s.add(action)
    await s.commit()
    return ToolResult(f"Proposed: {summary}. Waiting for the user to tap Confirm.", {"type": "confirm", "action_id": action.id})


async def _job_lines(s: AsyncSession, jobs: list[Job]) -> list[str]:
    """One line per job with the real reasons (fit, skills, gaps, flags) so the AI never has to guess."""
    ready = {d.job_id: d for d in (await s.execute(select(Draft).where(Draft.job_id.in_([j.id for j in jobs])))).scalars()}

    def state(j: Job) -> str:
        if j.apply_method != "email":
            return "apply via link"
        d = ready.get(j.id)
        return "no draft yet" if d is None else "draft needs review" if d.status == "needs_review" else "draft ready"

    def facts(j: Job) -> str:
        parts = [f"matched: {', '.join(j.matched_skills[:4])}" if j.matched_skills else "",
                 f"gaps: {', '.join(j.gaps[:3])}" if j.gaps else "",
                 f"flags: {'; '.join(j.flags)}" if j.flags else ""]
        return " · ".join(p for p in parts if p)

    return [f"#{j.id} fit {j.fit_score}/100 {post_info.verdict_label(j.verdict)}: {j.company} · {j.role} ({state(j)}) · {facts(j)}" for j in jobs]


async def list_jobs(s, user_id, ctx: Context, date: str = "today") -> ToolResult:
    d = report.parse_day(date, ctx.now.astimezone(report.IST).date())
    r = await report.day_report(s, user_id, d)
    if not r.posts:
        return ToolResult(f"No posts saved for {d:%d %b} yet. Telegram hasn't been read for that day "
                          f"(not 'no matches'). Call check_telegram to read it now.")
    if not r.matches:
        busy = f"; {r.pending} still being processed, ask again soon" if r.pending else ""
        return ToolResult(f"No jobs matching the resume on {d:%d %b} ({len(r.posts)} posts read{busy}).")
    jobs = [j for j, _ in r.matches]
    return ToolResult("\n".join([f"{len(jobs)} job(s) on {d:%d %b}:", *await _job_lines(s, jobs)]),
                      {"type": "jobs", "date": d.isoformat(), "job_ids": [j.id for j in jobs]})


PASTED_CHANNEL = "Pasted in chat"


async def analyze_pasted_job(s, user_id, ctx: Context) -> ToolResult:
    """The user's last message is a job post: run it through extract + fit (skipping the channel gates)."""
    text = ctx.last_user_message.replace("\x00", "")
    pre = prefilter(text)
    if not pre.keep:
        return ToolResult("The user's last message has no job text with an HR email or apply link. If they mean a job "
                          "shown earlier in this chat, use that job's #id from the earlier cards (e.g. write_email). "
                          "Otherwise ask them to send the job text with the HR email in the same message.")
    ch = (await s.execute(select(Channel).where(Channel.user_id == user_id, Channel.title == PASTED_CHANNEL,
                                                Channel.tg_chat_id == 0))).scalar_one_or_none()
    if ch is None:  # tg_chat_id 0 + disabled: never read from Telegram
        ch = Channel(user_id=user_id, tg_chat_id=0, title=PASTED_CHANNEL, enabled=False)
        s.add(ch)
        await s.flush()
    n = (await s.execute(select(func.coalesce(func.max(Post.tg_message_id), 0)).where(Post.channel_id == ch.id))).scalar_one()
    post = Post(user_id=user_id, channel_id=ch.id, tg_message_id=n + 1, text=text, posted_at=ctx.now,
                stage="matched", text_hash=pre.text_hash, emails=pre.emails, links=pre.links)  # asked on purpose
    s.add(post)
    await s.commit()

    stage = await graph.run_post(_sessionmaker(s), post.id)
    if stage == "matched":
        return ToolResult("Add a resume first (Setup → Resumes), then paste the job again.")
    if stage == "unreachable":
        return ToolResult("Can't reach the AI services right now (internet or provider down). Paste the job again in a minute.")
    if stage in ("rate_limited", "failed"):
        return ToolResult("The free AI is busy right now. Paste the job again in a minute.")
    jobs = (await s.execute(select(Job).where(Job.post_id == post.id).order_by(Job.idx))).scalars().all()
    if not jobs:
        return ToolResult("I couldn't find a job with an email address or apply link in that text.")
    return ToolResult("\n".join([f"{len(jobs)} job(s) from the pasted post:", *await _job_lines(s, list(jobs))]),
                      {"type": "jobs", "date": ctx.now.astimezone(report.IST).date().isoformat(),
                       "job_ids": [j.id for j in jobs]})


def _post_lines(rows: list[tuple[dict, float | None, list[Job]]], with_day: bool) -> list[str]:
    """One line per JOB (a post can list many); a post Leapvoy didn't read as a job gets one line saying why."""
    th = get_settings().match_threshold
    out = []
    for p, low, jobs in rows:
        when = (f"{p['posted_at'].astimezone(report.IST):%d %b} " if with_day else "") + post_info.ist_time(p)
        if jobs:
            for j in jobs:
                fit = (f"fit {j.fit_score}/100 {post_info.verdict_label(j.verdict)}" if j.fit_score is not None
                       else "being checked")
                if j.verdict == "SKIP":
                    fit += f" (Not a fit: {post_info.why_not(j)})"
                out.append(f"{when} job #{j.id} {j.role} · {j.company}: {fit} · apply by {j.apply_method}")
            continue
        extra = (f" (skipped before any fit check: text similarity {low:.3f}, the bar is {th}; not a fit score)"
                 if low is not None else "")
        out.append(f"{when} {p['title']}: {p['status']}{extra}")
    return out


async def _posts_result(s, user_id, posts: list[Post], head: str, with_day: bool) -> ToolResult:
    rows = await post_info.describe_all(s, user_id, posts)
    low = {p.id: p.match_score for p in posts if p.skip_reason == "low_match" and p.match_score is not None}
    by_post: dict[int, list[Job]] = {}
    for j in (await s.execute(select(Job).where(Job.user_id == user_id, Job.post_id.in_([p.id for p in posts]))
                              .order_by(Job.idx))).scalars():
        by_post.setdefault(j.post_id, []).append(j)
    cards = sum(len(by_post.get(r["id"], [])) or 1 for r in rows)
    fits = sum(1 for js in by_post.values() for j in js if j.verdict and j.verdict != "SKIP")
    lines = _post_lines([(r, low.get(r["id"]), by_post.get(r["id"], [])) for r in rows], with_day)
    note = (f"({cards} jobs in {len(rows)} posts; {fits} fit the resume. The app shows every job as its own card. "
            "Talk about JOBS, not posts: reply in 1-2 short sentences (e.g. how many jobs and the best fit) and do NOT "
            "list them.)")
    return ToolResult("\n".join([head, *lines, note]), {"type": "posts", "post_ids": [r["id"] for r in rows]})


async def list_posts(s, user_id, ctx: Context, date: str = "today") -> ToolResult:
    d = report.parse_day(date, ctx.now.astimezone(report.IST).date())
    start, end = report.day_bounds(d)
    posts = (await s.execute(select(Post).where(Post.user_id == user_id, Post.posted_at >= start, Post.posted_at < end)
                             .order_by(Post.posted_at.desc(), Post.tg_message_id.desc()))).scalars().all()
    if not posts:
        return ToolResult(f"No jobs saved for {d:%d %b} yet (Telegram not read for that day). Call check_telegram to read it now.")
    return await _posts_result(s, user_id, list(posts), f"Every job posted on {d:%d %b}, newest first:", False)


async def search_posts(s, user_id, ctx: Context, query: str, days: int = 7) -> ToolResult:
    """Any saved post (also skipped ones) matching every word of the query, newest first, with what happened to it."""
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1][:6]
    if not words:
        return ToolResult("Tell me a company or role to look for.")
    since = ctx.now - timedelta(days=max(1, min(days, 60)))
    in_text = and_(*[Post.text.ilike(f"%{w}%") for w in words])
    in_job = Post.id.in_(select(Job.post_id).where(  # or the company / role as the AI read them
        Job.user_id == user_id, *[func.concat(Job.company, " ", Job.role).ilike(f"%{w}%") for w in words]))
    q = select(Post).where(Post.user_id == user_id, Post.posted_at >= since, or_(in_text, in_job))
    posts = (await s.execute(q.order_by(Post.posted_at.desc()).limit(8))).scalars().all()
    if not posts:
        return ToolResult(f"No saved posts mention “{query}” in the last {days} days.")
    return await _posts_result(s, user_id, list(posts), f"{len(posts)} saved post(s) mention “{query}”:", True)


def _sessionmaker(s: AsyncSession) -> async_sessionmaker:
    """The pipeline opens its own sessions (one per stage)."""
    return async_sessionmaker(s.bind, expire_on_commit=False)


@dataclass(frozen=True)
class Fetched:
    """Result of "fetch this day": only posts Leapvoy didn't have are read, only unprocessed ones are checked."""
    problem: str | None = None  # e.g. Telegram not connected
    new_posts: int = 0
    checked: int = 0
    waiting: int = 0  # left for the background (time budget or low free allowance)
    paused: bool = False  # the free AI allowance is nearly used up


async def fetch_day(s: AsyncSession, user_id: uuid.UUID, now: datetime, d) -> Fetched:
    """Used by chat ("fetch today's jobs") and the Jobs screen's Fetch button."""
    session_str = await tg_store.load_session(s, user_id)
    if not session_str:
        return Fetched(problem="Telegram isn't connected yet (Setup → Channels), so there's nothing to read.")
    try:
        client = await reader.connect(session_str)
    except reader.SessionRevoked:
        return Fetched(problem="Telegram signed Leapvoy out. Log in to Telegram again (Setup → Channels).")
    try:
        new = await reader.catch_up(client, _sessionmaker(s), user_id)  # from the saved cursor: new posts only
        if d < now.astimezone(report.IST).date():  # an earlier day: read that day itself (missing or cleaned up)
            new += await reader.fetch_range(client, _sessionmaker(s), user_id, *report.day_bounds(d))
    finally:
        await client.disconnect()
    f = await check_day(s, user_id, now, d)
    return Fetched(new_posts=new, checked=f.checked, waiting=f.waiting, paused=f.paused)


async def check_day(s: AsyncSession, user_id: uuid.UUID, now: datetime, d) -> Fetched:
    """Check that India day's waiting posts (no Telegram read): Fetch, and the Jobs screen opening a day."""
    sm = _sessionmaker(s)
    async with sm() as s2:  # only that India day, and only posts not processed yet
        ids = await pipeline_store.next_posts(s2, user_id, FETCH_LIMIT, *report.day_bounds(d))
    if ids and not await usage.background_allowed(s, now):  # don't make the user wait on exhausted free limits
        return Fetched(waiting=len(ids), paused=True)
    deadline, done = time.monotonic() + FETCH_SECONDS, 0
    for post_id in ids:
        if time.monotonic() >= deadline:
            break
        await graph.run_post(sm, post_id)  # locked per post: never twice alongside the background worker
        done += 1
    return Fetched(checked=done, waiting=len(ids) - done)


async def check_telegram(s, user_id, ctx: Context, date: str = "today") -> ToolResult:
    d = report.parse_day(date, ctx.now.astimezone(report.IST).date())
    f = await fetch_day(s, user_id, ctx.now, d)
    if f.problem:
        return ToolResult(f.problem)
    if f.paused:
        note = (f" Today's free AI allowance is nearly used up, so {f.waiting} post(s) will be checked automatically "
                f"when it refills.")
    else:
        note = f" {f.waiting} post(s) still being processed. They'll show up in Jobs shortly." if f.waiting else ""
    jobs = await list_jobs(s, user_id, ctx, d.isoformat())
    return ToolResult(f"Read Telegram: {f.new_posts} new post(s).{note} " + jobs.text, jobs.card)


async def write_email(s, user_id, ctx: Context, job_id: int, rewrite: bool = False) -> ToolResult:
    job = await _job(s, user_id, job_id)
    existing = (await s.execute(select(Draft).where(Draft.job_id == job_id))).scalar_one_or_none() if job else None
    if existing and not rewrite and not await drafts.is_outdated(s, existing):  # don't burn AI quota / replace a reviewed draft
        note = f" It needs review: {'; '.join(existing.issues)}" if existing.issues else ""
        return ToolResult(f"Draft for job #{job_id} is already ready: {existing.subject}.{note}",
                          {"type": "draft", "job_id": job_id})
    try:
        draft = await drafts.write_draft(s, user_id, job_id)
    except drafts.JobNotFound:
        return ToolResult(f"No job #{job_id}.")
    except drafts.NotAnEmailJob:
        return ToolResult(f"Job #{job_id} is applied to through a link or form, not by email.")
    except drafts.NoResume:
        return ToolResult("Add a resume first (Setup → Resumes).")
    except drafts.ProfileIncomplete as e:
        return ToolResult(f"The user's profile is missing their {', '.join(e.missing)}, which every email ends with. "
                          "Ask them to add it first.")
    note = f" It needs review: {'; '.join(draft.issues)}" if draft.issues else ""
    return ToolResult(f"Draft for job #{job_id} is ready: {draft.subject}.{note}", {"type": "draft", "job_id": job_id})


async def schedule_email(s, user_id, ctx: Context, job_id: int, when: str = "now") -> ToolResult:
    job = await _job(s, user_id, job_id)
    if job is None:
        return ToolResult(f"No job #{job_id}.")
    draft = (await s.execute(select(Draft).where(Draft.job_id == job.id))).scalar_one_or_none()
    if draft is None:
        return ToolResult(f"Job #{job_id} has no email yet. Write it first.")
    if draft.status == "needs_review":
        return ToolResult(f"The email for job #{job_id} needs review first: {'; '.join(draft.issues)}")
    if await drafts.is_outdated(s, draft):
        return ToolResult(f"The email for job #{job_id} was written from an older resume. Rewrite it first.")
    if await senders.default_sender(s, user_id) is None:
        return ToolResult("No sender email connected yet (Setup → Email accounts).")
    try:
        at = parse_when(when, ctx.now)
    except ValueError as e:
        return ToolResult(str(e))
    test = await outbox.is_test_mode(s, user_id)
    to = draft.to_emails  # every HR address of the post, together in one email
    at_text = "now" if when.strip().lower() == "now" else _when_text(at)
    try:  # the same notes as the job card's pop-up, shown on the Confirm card: confirming = "send anyway"
        notes = await outbox.send_notes(s, user_id, job, [e.lower() for e in to], ctx.now, test)
    except outbox.NotAllowed as e:
        return ToolResult(str(e))
    summary = f"Send “{draft.subject}” to {', '.join(to)} ({job.company} · {job.role}) {at_text}" + (TEST_NOTE if test else "")
    summary += "".join(f"\n⚠ {n}" for n in notes)
    return await _propose(s, user_id, "schedule", {"job_id": job.id, "to": to, "when": at.isoformat()}, summary)


async def list_scheduled(s, user_id, ctx: Context, date: str | None = None) -> ToolResult:
    q = select(Send, Job).join(Job, Send.job_id == Job.id).where(Send.user_id == user_id, Send.status == "scheduled")
    if date:
        start, end = report.day_bounds(report.parse_day(date, ctx.now.astimezone(report.IST).date()))
        q = q.where(Send.send_at >= start, Send.send_at < end)
    rows = (await s.execute(q.order_by(Send.send_at))).tuples().all()
    if not rows:
        return ToolResult("Nothing scheduled" + (f" for {date}." if date else "."))
    lines = [f"#{send.id} {_when_text(send.send_at)}: {job.company} · {job.role} → {', '.join(send.to_emails or [send.to_email])}"
             + (" [TEST]" if send.test_mode else "") for send, job in rows]
    return ToolResult(f"{len(rows)} scheduled:\n" + "\n".join(lines), {"type": "sends", "send_ids": [x.id for x, _ in rows]})


async def _scheduled_send(s, user_id, send_id: int) -> tuple[Send, Job] | None:
    row = (await s.execute(select(Send, Job).join(Job, Send.job_id == Job.id).where(
        Send.id == send_id, Send.user_id == user_id, Send.status == "scheduled"))).first()
    return tuple(row) if row else None


async def cancel_email(s, user_id, ctx: Context, send_id: int) -> ToolResult:
    row = await _scheduled_send(s, user_id, send_id)
    if row is None:
        return ToolResult(f"No scheduled email #{send_id}.")
    send, job = row
    return await _propose(s, user_id, "cancel", {"send_id": send.id},
                          f"Cancel the email to {send.to_email} ({job.company} · {job.role}) at {_when_text(send.send_at)}")


async def reschedule_email(s, user_id, ctx: Context, send_id: int, when: str) -> ToolResult:
    row = await _scheduled_send(s, user_id, send_id)
    if row is None:
        return ToolResult(f"No scheduled email #{send_id}.")
    try:
        at = parse_when(when, ctx.now)
    except ValueError as e:
        return ToolResult(str(e))
    send, job = row
    return await _propose(s, user_id, "reschedule", {"send_id": send.id, "when": at.isoformat()},
                          f"Move the email to {send.to_email} ({job.company} · {job.role}) to {_when_text(at)}")


async def stats(s, user_id, ctx: Context, days: int = 7) -> ToolResult:
    from app.api.stats import compute  # same numbers as the Stats screen

    st = await compute(s, user_id, max(1, min(days, 365)), now=ctx.now)
    f = st["funnel"]
    test = f" (+{st['test_sent']} test-mode email(s) to your own inbox)" if st["test_sent"] else ""
    rate = f" ({f['reply_rate']}% reply rate)" if f["sent"] else ""
    return ToolResult(f"Last {days} days: {f['posts']} post(s) read, {f['checked']} checked by AI, {f['fit']} job(s) "
                      f"fit your resume, {f['sent']} email(s) sent{test}, {f['replies']} reply(ies){rate}.")


async def remember(s, user_id, ctx: Context, fact: str) -> ToolResult:
    if ctx.incognito:
        return ToolResult("Not saved: this is an incognito chat.")
    s.add(Memory(user_id=user_id, text=fact.strip()[:300]))
    await s.commit()
    return ToolResult(f"Saved to memory: {fact.strip()}")


_REGISTRY = {f.__name__: f for f in (list_jobs, list_posts, search_posts, check_telegram, analyze_pasted_job, write_email, schedule_email, list_scheduled, cancel_email,
                                     reschedule_email, stats, remember)}


async def run_tool(s: AsyncSession, user_id: uuid.UUID, name: str, args: dict, ctx: Context) -> ToolResult:
    fn = _REGISTRY.get(name)
    if fn is None:
        return ToolResult(f"Unknown tool {name}.")
    try:
        return await fn(s, user_id, ctx, **args)
    except TypeError as e:  # the AI passed wrong arguments
        return ToolResult(f"Couldn't run {name}: {e}")
