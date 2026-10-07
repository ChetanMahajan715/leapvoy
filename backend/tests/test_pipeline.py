import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.accounts import profile
from app.db.models import Job, Post
from app.llm.router import AIUnreachable, LLMUnavailable, RateLimited
from app.llm.schemas import ExtractedPost, FitCheck, FitRow, JobPost
from app.pipeline import graph
from app.pipeline import store as pstore
from app.telegram import store as tstore
from app.telegram.store import IncomingPost
from tests.conftest import requires_db

pytestmark = requires_db
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
AI_POST = "Company - Acme AI | Role - AI Engineer | Skills: Python, LLMs | Mail hr@acme.ai"


class FakeLLM:
    """Stands in for router.structured. Returns queued extraction / a fit per call; records calls."""

    def __init__(self, jobs=None, fit=None, fail_fit=0):
        self.jobs = jobs if jobs is not None else [job("Acme AI", ["hr@acme.ai"])]
        self.fit = fit or fitcheck(82, "STRONG MATCH")
        self.fail_fit = fail_fit
        self.calls: list[str] = []

    async def __call__(self, tier, messages, response_model, **kw):
        self.calls.append(response_model.__name__)
        if response_model is ExtractedPost:
            return ExtractedPost(jobs=self.jobs)
        if self.fail_fit:
            self.fail_fit -= 1
            raise LLMUnavailable("all models busy")
        return self.fit


def job(company, emails, role="AI Engineer", links=()):
    return JobPost(company=company, role=role, hr_emails=emails, apply_links=list(links), must_have_skills=["Python"])


def fitcheck(score, verdict, family="target", years=None):
    return FitCheck(
        score=score, verdict=verdict, role_family=family, min_years_required=years, matched_skills=["Python"],
        gaps=[], flags=[],
        rows=[FitRow(requirement="Python", fit="Strong", note="all projects")],
    )


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(graph, "structured", fake)
    return fake


@pytest.fixture
def match(monkeypatch):
    """Resume similarity per test (real embeddings are covered in test_resume_match)."""
    state = {"score": 0.8}

    async def fake_match(s, user_id, text):
        return state["score"]

    async def fake_resume(s, user_id):
        return None if state["score"] is None else SimpleNamespace(id=None, text="AI Engineer resume: Python, LangChain")

    monkeypatch.setattr(graph, "match_score", fake_match)
    monkeypatch.setattr(graph, "active_resume", fake_resume)
    return state


async def make_posts(sm, texts, email="a@x.com", chat_id=-1001):
    async with sm() as s:
        uid = await tstore.get_or_create_user(s, email)
        await tstore.upsert_channels(s, uid, [(chat_id, f"ch{chat_id}", None)])
        await tstore.set_enabled(s, uid, [chat_id], True)
        ch = await tstore.get_enabled_channel(s, uid, chat_id)
        start = len((await s.execute(select(Post))).all())
        await tstore.save_posts(s, uid, ch.id, [IncomingPost(start + i + 1, t, NOW) for i, t in enumerate(texts)])
        await profile.set_profile(s, uid, {"home_city": "Pune", "education": "2026 batch BCA"})
        ids = (await s.execute(select(Post.id).where(Post.user_id == uid).order_by(Post.id))).scalars().all()
    return uid, ids[-len(texts):]


async def post(sm, post_id):
    async with sm() as s:
        return await s.get(Post, post_id)


async def jobs(sm, post_id):
    async with sm() as s:
        return (await s.execute(select(Job).where(Job.post_id == post_id).order_by(Job.idx))).scalars().all()


async def test_post_without_email_or_link_is_skipped_without_ai(sm, llm, match):
    _, [pid] = await make_posts(sm, ["Special group rules: share your interview updates with @admin"])
    await graph.run_post(sm, pid)
    p = await post(sm, pid)
    assert (p.stage, p.skip_reason) == ("skipped", "no_apply_method") and llm.calls == []


LINK_POST = "Company - Beta AI | Role - AI Engineer | Apply: https://docs.google.com/forms/d/e/ABC/viewform?usp=header"


async def test_link_only_job_is_kept_with_its_link(sm, llm, match):
    llm.jobs = [job("Beta AI", [], links=["https://docs.google.com/forms/d/e/ABC/viewform?usp=header"])]
    _, [pid] = await make_posts(sm, [LINK_POST])
    await graph.run_post(sm, pid)
    [j] = await jobs(sm, pid)
    assert (j.apply_method, j.hr_emails, j.apply_links) == (
        "link", [], ["https://docs.google.com/forms/d/e/ABC/viewform?usp=header"])
    assert j.fit_score == 82 and (await post(sm, pid)).stage == "scored"


async def test_invented_links_removed_and_shortened_links_restored(sm, llm, match):
    llm.jobs = [job("Beta AI", [], links=["https://docs.google.com/forms/d/e/ABC/viewform", "https://evil.example/x"])]
    _, [pid] = await make_posts(sm, [LINK_POST])
    await graph.run_post(sm, pid)
    [j] = await jobs(sm, pid)
    assert j.apply_links == ["https://docs.google.com/forms/d/e/ABC/viewform?usp=header"]  # the post's real link


async def test_email_job_is_marked_email(sm, llm, match):
    _, [pid] = await make_posts(sm, [AI_POST])
    await graph.run_post(sm, pid)
    assert (await jobs(sm, pid))[0].apply_method == "email"


async def test_repost_in_another_channel_is_duplicate(sm, llm, match):
    _, [first] = await make_posts(sm, [AI_POST], chat_id=-1001)
    uid, [second] = await make_posts(sm, ["🚨 " + AI_POST.upper()], chat_id=-1002)
    async with sm() as s:
        assert await pstore.next_posts(s, uid, 10) == [first, second]  # oldest first → original wins
    await graph.run_post(sm, first)
    await graph.run_post(sm, second)
    assert (await post(sm, first)).stage == "scored"
    assert (await post(sm, second)).skip_reason == "duplicate"


async def test_low_match_is_skipped_and_score_kept(sm, llm, match):
    match["score"] = 0.31
    _, [pid] = await make_posts(sm, [AI_POST])
    await graph.run_post(sm, pid)
    p = await post(sm, pid)
    assert (p.stage, p.skip_reason, round(p.match_score, 2)) == ("skipped", "low_match", 0.31)
    assert llm.calls == []


async def test_without_resume_post_waits(sm, llm, match):
    match["score"] = None
    _, [pid] = await make_posts(sm, [AI_POST])
    await graph.run_post(sm, pid)
    p = await post(sm, pid)
    assert (p.stage, p.attempts) == ("new", 0) and llm.calls == []


async def test_invented_emails_are_removed(sm, llm, match):
    llm.jobs = [job("Acme AI", ["hr@acme.ai", "ceo@acme.ai"]), job("Ghost Inc", ["jobs@ghost.io"])]
    _, [pid] = await make_posts(sm, [AI_POST])
    await graph.run_post(sm, pid)
    [only] = await jobs(sm, pid)
    assert (only.company, only.hr_emails) == ("Acme AI", ["hr@acme.ai"])


async def test_post_with_no_real_email_left_is_skipped(sm, llm, match):
    llm.jobs = [job("Ghost Inc", ["jobs@ghost.io"])]
    _, [pid] = await make_posts(sm, [AI_POST])
    await graph.run_post(sm, pid)
    assert (await post(sm, pid)).skip_reason == "no_valid_job"


async def test_multi_job_post_scores_every_job(sm, llm, match):
    text = "1) Company - A | mail a@a.ai\n2) Company - B | mail b@b.ai\n3) Company - C | mail c@c.ai"
    llm.jobs = [job("A", ["a@a.ai"]), job("B", ["b@b.ai"]), job("C", ["c@c.ai"])]
    _, [pid] = await make_posts(sm, [text])
    await graph.run_post(sm, pid)
    rows = await jobs(sm, pid)
    assert [j.company for j in rows] == ["A", "B", "C"]
    assert all(j.fit_score == 82 and j.verdict == "STRONG MATCH" and j.fit_rows for j in rows)
    assert (await post(sm, pid)).stage == "scored"
    assert llm.calls == ["ExtractedPost", "FitCheck", "FitCheck", "FitCheck"]


async def test_too_much_experience_forces_skip(sm, llm, match):
    llm.fit = fitcheck(75, "STRONG MATCH", years=6)  # "6+ years" → your rule: never
    _, [pid] = await make_posts(sm, [AI_POST])
    await graph.run_post(sm, pid)
    assert (await jobs(sm, pid))[0].verdict == "SKIP"


async def test_scored_post_is_not_reprocessed(sm, llm, match):
    _, [pid] = await make_posts(sm, [AI_POST])
    await graph.run_post(sm, pid)
    llm.calls.clear()
    await graph.run_post(sm, pid)
    assert llm.calls == []


async def test_failure_resumes_at_failed_stage(sm, llm, match):
    llm.fail_fit = 1
    _, [pid] = await make_posts(sm, [AI_POST])
    await graph.run_post(sm, pid)
    p = await post(sm, pid)
    assert (p.stage, p.attempts) == ("extracted", 1)
    llm.calls.clear()
    await graph.run_post(sm, pid)
    assert llm.calls == ["FitCheck"]  # extraction was not paid for twice
    assert (await post(sm, pid)).stage == "scored"


async def test_rate_limit_is_not_counted_as_a_failure(sm, llm, match, monkeypatch):
    async def busy(*a, **kw):
        raise RateLimited("free tier busy")

    _, [pid] = await make_posts(sm, [AI_POST])
    monkeypatch.setattr(graph, "structured", busy)
    for _ in range(4):
        await graph.run_post(sm, pid)
    p = await post(sm, pid)
    assert (p.stage, p.attempts) == ("matched", 0)  # waits for the next round, never marked as error


async def test_unreachable_ai_is_not_counted_as_a_failure(sm, llm, match, monkeypatch):
    """No internet / providers down: the post waits and is retried later, never marked 'AI check failed'."""
    async def offline(*a, **kw):
        raise AIUnreachable("no internet")

    _, [pid] = await make_posts(sm, [AI_POST])
    monkeypatch.setattr(graph, "structured", offline)
    for _ in range(4):
        assert await graph.run_post(sm, pid) == "unreachable"
    p = await post(sm, pid)
    assert (p.stage, p.attempts) == ("matched", 0)


async def test_gives_up_after_three_failures(sm, llm, match):
    llm.fail_fit = 5
    _, [pid] = await make_posts(sm, [AI_POST])
    for _ in range(3):
        await graph.run_post(sm, pid)
    p = await post(sm, pid)
    assert (p.stage, p.attempts) == ("error", 3)


async def test_next_posts_never_returns_other_users_posts(sm, llm, match):
    a, _ = await make_posts(sm, [AI_POST], email="a@x.com", chat_id=-1001)
    b, [b_post] = await make_posts(sm, ["Other job, mail hr@b.io"], email="b@x.com", chat_id=-2001)
    async with sm() as s:
        assert await pstore.next_posts(s, b, 10) == [b_post]
        assert b_post not in await pstore.next_posts(s, a, 10)


async def test_one_post_is_never_processed_twice_at_the_same_time(sm, llm, match, monkeypatch):
    """Chat's 'check Telegram' and the background pipeline can reach the same post together."""
    _, [pid] = await make_posts(sm, [AI_POST])
    slow = llm.__call__

    async def slow_llm(tier, messages, response_model, **kw):
        await asyncio.sleep(0.3)  # both runs overlap
        return await slow(tier, messages, response_model, **kw)

    monkeypatch.setattr(graph, "structured", slow_llm)
    stages = await asyncio.gather(graph.run_post(sm, pid), graph.run_post(sm, pid))
    assert sorted(stages) == ["busy", "scored"]
    assert llm.calls == ["ExtractedPost", "FitCheck"]  # the AI was asked once, not twice
    assert len(await jobs(sm, pid)) == 1


async def test_clearly_unrelated_title_is_skipped_without_the_fit_call(sm, llm, match):
    """Saves ~3k tokens per job: the user's rules would force SKIP for this title anyway."""
    llm.jobs = [job("Acme", ["hr@acme.ai"], role="Business Analyst")]
    _, [pid] = await make_posts(sm, [AI_POST])
    assert await graph.run_post(sm, pid) == "scored"
    [j] = await jobs(sm, pid)
    assert llm.calls == ["ExtractedPost"]  # no FitCheck
    assert j.verdict == "SKIP" and j.fit_score is not None and any("not a target role" in f for f in j.flags)


async def test_ai_titles_with_unrelated_words_still_get_the_fit_call(sm, llm, match):
    llm.jobs = [job("Acme", ["hr@acme.ai"], role="AI Product Design Engineer")]
    _, [pid] = await make_posts(sm, [AI_POST])
    await graph.run_post(sm, pid)
    assert llm.calls == ["ExtractedPost", "FitCheck"]


async def test_job_keeps_the_posts_own_link_when_the_ai_forgets_it(sm, llm, match):
    """Seen live (1 Oct): a backup model returned the Kiwimesh job without its Google Form link → job was lost."""
    llm.jobs = [job("Kiwimesh", [], role="AI Generalist Intern")]  # the AI 'forgot' the link
    form = "https://docs.google.com/forms/d/e/1FAIpQLSf3PllJkBcJTTPW__BO5Zy8DuJKwQeRb88GLFjMpjfdL2eJVg/viewform"
    _, [pid] = await make_posts(sm, [f"Company - Kiwimesh Role - AI Generalist Intern. How to Apply: {form}"])
    assert await graph.run_post(sm, pid) == "scored"
    [j] = await jobs(sm, pid)
    assert j.apply_links == [form] and j.apply_method == "link"


async def test_single_job_keeps_the_posts_email_when_the_ai_forgets_it(sm, llm, match):
    llm.jobs = [job("Acme AI", [])]
    _, [pid] = await make_posts(sm, [AI_POST])  # the post says: Mail hr@acme.ai
    assert await graph.run_post(sm, pid) == "scored"
    [j] = await jobs(sm, pid)
    assert j.hr_emails == ["hr@acme.ai"]


async def test_several_jobs_without_their_own_links_are_not_given_a_guessed_one(sm, llm, match):
    """With 2+ jobs we can't know whose link it is → don't guess (unchanged behaviour)."""
    llm.jobs = [job("A", []), job("B", [])]
    _, [pid] = await make_posts(sm, ["Two roles. Apply: https://forms.gle/abc123"])
    assert await graph.run_post(sm, pid) == "skipped"


MULTI_POST = "\n\n".join(
    [f"{i}) Company - Firm{i}\nRole - {r}\nSkills: Python\nApply: hr{i}@firm{i}.com" for i, r in
     enumerate(["Software Developer Intern", "Business Analyst", "Product Intern", "Sales Associate",
                "Content Writer", "ML Engineer"], start=1)])


async def test_multi_job_post_matches_every_job_not_just_the_start(sm, llm, monkeypatch):
    seen = {}

    async def fake_match(s, user_id, texts):
        seen["texts"] = texts
        return 0.8 if any("ML Engineer" in t for t in texts) else 0.3  # only the last job fits

    async def fake_resume(s, user_id):
        return SimpleNamespace(id=None, text="ML resume")

    monkeypatch.setattr(graph, "match_score", fake_match)
    monkeypatch.setattr(graph, "active_resume", fake_resume)
    llm.jobs = [job(f"Firm{i}", [f"hr{i}@firm{i}.com"], role=f"Role {i}") for i in range(1, 7)]
    _, [pid] = await make_posts(sm, [MULTI_POST])
    await graph.run_post(sm, pid)
    assert len(seen["texts"]) == 7  # the post start + each of the 6 job blocks
    assert (await post(sm, pid)).stage == "scored" and len(await jobs(sm, pid)) == 6


async def test_missed_jobs_are_read_block_by_block_and_each_scored_on_its_own_text(sm, monkeypatch, match):
    prompts: list[str] = []

    async def fake(tier, messages, response_model, **kw):
        text = messages[-1]["content"]
        if response_model is ExtractedPost:
            if text == MULTI_POST:
                return ExtractedPost(jobs=[job("Firm1", ["hr1@firm1.com"])])  # the AI saw only the first job
            i = int(text.split(")")[0])
            return ExtractedPost(jobs=[job(f"Firm{i}", [f"hr{i}@firm{i}.com"], role=f"Role {i}")])
        prompts.append(text)
        return fitcheck(70, "APPLY")

    monkeypatch.setattr(graph, "structured", fake)
    _, [pid] = await make_posts(sm, [MULTI_POST])
    await graph.run_post(sm, pid)
    found = await jobs(sm, pid)
    assert [j.company for j in found] == [f"Firm{i}" for i in range(1, 7)]
    assert len(prompts) == 6
    assert "Firm3" in prompts[2] and "Firm1" not in prompts[2] and "Firm4" not in prompts[2]  # its own block only
