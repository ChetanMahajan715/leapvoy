from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.chat import actions, tools
from app.db.models import Channel, Draft, Job, Memory, PendingAction, Post, Send
from app.pipeline import report
from app.telegram.store import get_or_create_user, save_session
from tests.conftest import requires_db
from tests.test_outbox import NOW, master_key, setup, smtp  # noqa: F401 (fixtures)
from tests.test_pipeline import llm, match  # noqa: F401 (fixtures)

pytestmark = requires_db


def ctx(incognito=False):
    return tools.Context(now=NOW, incognito=incognito, last_user_message="")


async def run(db, uid, name, **args):
    return await tools.run_tool(db, uid, name, args, ctx())


async def count(db, model):
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_list_jobs_gives_a_card_with_the_days_jobs(db, smtp):
    uid, jobs = await setup(db, n_jobs=2)
    r = await run(db, uid, "list_jobs", date="2026-09-30")
    assert r.card == {"type": "jobs", "date": "2026-09-30", "job_ids": sorted(jobs)}
    assert "Company0" in r.text and "Company1" in r.text


async def test_scheduling_only_proposes_until_confirmed(db, smtp):
    uid, [job] = await setup(db)
    r = await run(db, uid, "schedule_email", job_id=job, when="now")
    assert r.card["type"] == "confirm" and await count(db, Send) == 0  # nothing sent/scheduled yet
    action = await db.get(PendingAction, r.card["action_id"])
    assert "hr0@company0.com" in action.summary and "TEST MODE" in action.summary
    done = await actions.confirm(db, uid, action.id, now=NOW)
    assert done.status == "done" and await count(db, Send) == 1


async def test_confirming_twice_does_not_schedule_twice(db, smtp):
    uid, [job] = await setup(db)
    r = await run(db, uid, "schedule_email", job_id=job, when="tomorrow 10am")
    await actions.confirm(db, uid, r.card["action_id"], now=NOW)
    with pytest.raises(actions.ActionError, match="already"):
        await actions.confirm(db, uid, r.card["action_id"], now=NOW)
    assert await count(db, Send) == 1


async def test_dismissed_proposal_sends_nothing(db, smtp):
    uid, [job] = await setup(db)
    r = await run(db, uid, "schedule_email", job_id=job, when="now")
    await actions.dismiss(db, uid, r.card["action_id"])
    with pytest.raises(actions.ActionError):
        await actions.confirm(db, uid, r.card["action_id"], now=NOW)
    assert await count(db, Send) == 0


async def test_draft_needing_review_is_not_proposed(db, smtp):
    uid, [job] = await setup(db, draft_status="needs_review")
    r = await run(db, uid, "schedule_email", job_id=job, when="now")
    assert r.card is None and "review" in r.text and await count(db, PendingAction) == 0


async def test_cancel_goes_through_confirm_too(db, smtp):
    uid, [job] = await setup(db)
    proposal = await run(db, uid, "schedule_email", job_id=job, when="tomorrow 10am")
    await actions.confirm(db, uid, proposal.card["action_id"], now=NOW)
    send_id = (await db.execute(select(Send.id))).scalar_one()
    r = await run(db, uid, "cancel_email", send_id=send_id)
    assert (await db.get(Send, send_id)).status == "scheduled"  # not yet
    await actions.confirm(db, uid, r.card["action_id"], now=NOW)
    await db.refresh(await db.get(Send, send_id))
    assert (await db.get(Send, send_id)).status == "cancelled"


async def test_list_scheduled_shows_waiting_emails(db, smtp):
    uid, [job] = await setup(db)
    p = await run(db, uid, "schedule_email", job_id=job, when="tomorrow 10am")
    await actions.confirm(db, uid, p.card["action_id"], now=NOW)
    r = await run(db, uid, "list_scheduled")
    assert r.card["type"] == "sends" and len(r.card["send_ids"]) == 1 and "Company0" in r.text


async def test_other_users_jobs_and_actions_are_out_of_reach(db, smtp):
    uid, [job] = await setup(db, "a@x.com")
    other = await get_or_create_user(db, "b@x.com")
    r = await run(db, other, "schedule_email", job_id=job, when="now")
    assert r.card is None and "No job" in r.text
    mine = await run(db, uid, "schedule_email", job_id=job, when="now")
    with pytest.raises(actions.ActionError, match="No such"):
        await actions.confirm(db, other, mine.card["action_id"], now=NOW)


async def test_remember_saves_a_preference_except_in_incognito(db, smtp):
    uid, _ = await setup(db)
    await tools.run_tool(db, uid, "remember", {"fact": "Prefer sending at 10 AM"}, ctx())
    r = await tools.run_tool(db, uid, "remember", {"fact": "secret"}, ctx(incognito=True))
    assert "incognito" in r.text.lower()
    assert [m.text for m in (await db.execute(select(Memory))).scalars()] == ["Prefer sending at 10 AM"]


async def test_stats_counts_the_last_days(db, smtp):
    uid, jobs = await setup(db, n_jobs=2)
    r = await tools.run_tool(db, uid, "stats", {"days": 7}, tools.Context(now=NOW + timedelta(days=1), incognito=False,
                                                                       last_user_message=""))
    assert "2 job" in r.text


async def test_unknown_tool_is_reported_not_crashing(db, smtp):
    uid, _ = await setup(db)
    r = await run(db, uid, "delete_everything")
    assert "Unknown" in r.text and r.card is None


async def test_write_email_tool_makes_a_draft_card(db, smtp, monkeypatch):
    uid, [job] = await setup(db)

    async def fake_write(s, user_id, job_id):
        return await s.get(Draft, (await s.execute(select(Draft.id).where(Draft.job_id == job_id))).scalar_one())

    monkeypatch.setattr(tools.drafts, "write_draft", fake_write)
    r = await run(db, uid, "write_email", job_id=job)
    assert r.card == {"type": "draft", "job_id": job}


async def test_existing_up_to_date_draft_is_reused_not_rewritten(db, smtp, monkeypatch):
    uid, [job] = await setup(db)
    calls = []

    async def spy_write(s, user_id, job_id):
        calls.append(job_id)

    monkeypatch.setattr(tools.drafts, "write_draft", spy_write)
    r = await run(db, uid, "write_email", job_id=job)
    assert calls == [] and r.card == {"type": "draft", "job_id": job} and "already" in r.text


async def test_list_jobs_gives_the_ai_real_reasons(db, smtp):
    uid, [job] = await setup(db)
    j = await db.get(Job, job)
    j.matched_skills, j.gaps, j.flags = ["Python", "LangChain"], ["Kubernetes"], ["relocation needed: Mumbai"]
    await db.commit()
    r = await run(db, uid, "list_jobs", date="2026-09-30")
    assert "Python, LangChain" in r.text and "Kubernetes" in r.text and "relocation" in r.text and "draft ready" in r.text


# --- paste a job --------------------------------------------------------------------------

PASTED = "Hiring AI Engineer at Acme AI, 0-2 years, Python + LLMs. Send your resume to hr@acme.ai"


async def paste(db, uid, text=PASTED):
    return await tools.run_tool(db, uid, "analyze_pasted_job", {},
                                tools.Context(now=NOW, incognito=False, last_user_message=text))


async def test_pasted_job_is_fit_checked_even_below_the_match_bar(db, smtp, llm, match):
    uid, _ = await setup(db)
    match["score"] = 0.1  # the user asked on purpose: channel gates don't apply
    r = await paste(db, uid)
    [job] = (await db.execute(select(Job).where(Job.company == "Acme AI"))).scalars()
    assert r.card == {"type": "jobs", "date": "2026-09-30", "job_ids": [job.id]}
    assert job.fit_score == 82 and "fit 82/100" in r.text and llm.calls == ["ExtractedPost", "FitCheck"]
    ch = await db.get(Channel, (await db.get(Post, job.post_id)).channel_id)
    assert ch.title == "Pasted in chat" and not ch.enabled  # the Telegram reader never touches it


async def test_pasting_twice_uses_one_pasted_channel(db, smtp, llm, match):
    uid, _ = await setup(db)
    await paste(db, uid)
    await paste(db, uid, PASTED + " (reposted)")
    assert (await db.execute(select(func.count()).where(Channel.title == "Pasted in chat"))).scalar_one() == 1


async def test_text_without_email_or_link_is_explained_without_ai(db, smtp, llm, match):
    uid, _ = await setup(db)
    r = await paste(db, uid, "We are hiring an AI engineer, DM me")
    assert r.card is None and "email or apply link" in r.text and llm.calls == []


# --- check Telegram now + honest empty days -----------------------------------------------

async def test_empty_day_says_nothing_was_read_not_no_matches(db, smtp):
    uid, _ = await setup(db)
    r = await run(db, uid, "list_jobs", date="2026-09-25")
    assert "no posts" in r.text.lower() and "check_telegram" in r.text


@pytest.fixture
def telegram(monkeypatch):
    seen = {"fetched": 0, "ran": None}

    async def fake_connect(session_str):
        return SimpleNamespace(disconnect=_noop)

    async def fake_catch_up(client, sm, user_id):
        seen["fetched"] += 1
        return 3

    async def fake_next_posts(s, user_id, limit, since=None, until=None):
        seen["ran"] = (limit, since, until)
        return [101, 102, 103]

    async def fake_run_post(sm, post_id):
        seen["processed"].append(post_id)
        return "scored"

    seen["processed"] = []
    monkeypatch.setattr(tools.reader, "connect", fake_connect)
    monkeypatch.setattr(tools.reader, "catch_up", fake_catch_up)
    monkeypatch.setattr(tools.pipeline_store, "next_posts", fake_next_posts)
    monkeypatch.setattr(tools.graph, "run_post", fake_run_post)
    return seen


async def _noop():
    return None


async def test_check_telegram_fetches_processes_that_day_and_shows_jobs(db, smtp, telegram):
    uid, jobs = await setup(db)
    await save_session(db, uid, "+910000000000", "session-string")
    r = await run(db, uid, "check_telegram", date="2026-09-30")
    assert telegram["fetched"] == 1 and "3 new post" in r.text
    assert telegram["ran"][1:] == report.day_bounds(date(2026, 9, 30))  # only that India day
    assert r.card == {"type": "jobs", "date": "2026-09-30", "job_ids": jobs}


async def test_check_telegram_without_login_explains(db, smtp, telegram):
    uid, _ = await setup(db)
    r = await run(db, uid, "check_telegram")
    assert "Telegram isn't connected" in r.text and telegram["fetched"] == 0


async def test_check_telegram_stops_after_its_time_budget(db, smtp, telegram, monkeypatch):
    """Chat must not hang for minutes on a backlog: what's left continues in the background pipeline."""
    uid, _ = await setup(db)
    await save_session(db, uid, "+910000000000", "session-string")
    monkeypatch.setattr(tools, "FETCH_SECONDS", 0)
    r = await run(db, uid, "check_telegram", date="2026-09-30")
    assert telegram["processed"] == [] and "3 post(s) still being processed" in r.text


async def test_check_telegram_answers_fast_when_the_free_allowance_is_low(db, smtp, telegram, monkeypatch):
    uid, _ = await setup(db)
    await save_session(db, uid, "+910000000000", "session-string")

    async def low(s, now):
        return False

    monkeypatch.setattr(tools.usage, "background_allowed", low)
    r = await run(db, uid, "check_telegram", date="2026-09-30")
    assert telegram["processed"] == [] and "free AI allowance" in r.text and "3 post(s)" in r.text


async def test_search_posts_finds_skipped_posts_and_says_why(db, smtp):
    """'Is there a Blinkit Associate Program Manager job?', even skipped posts are found, with the reason."""
    uid, [job] = await setup(db)
    ch = (await db.execute(select(Channel).where(Channel.user_id == uid))).scalars().first()
    db.add_all([
        Post(user_id=uid, channel_id=ch.id, tg_message_id=50, posted_at=NOW, stage="skipped", skip_reason="low_match",
             match_score=0.644, text="Company - Blinkit Role - Associate Program Manager Location - Gurgaon"),
        Post(user_id=uid, channel_id=ch.id, tg_message_id=51, posted_at=NOW, stage="skipped", skip_reason="no_valid_job",
             text="Company - Blinkit Role - Associate Program Manager (Last Mile)"),
    ])
    j = await db.get(Job, job)
    j.company, j.role, j.verdict, j.flags = "Blinkit", "Program Manager", "SKIP", ["batch not eligible"]
    await db.commit()
    r = await run(db, uid, "search_posts", query="blinkit program manager")
    assert "Associate Program Manager" in r.text and "Weak match with your resume" in r.text and "No email or apply link" in r.text
    assert f"#{job}" in r.text and "Not a fit" in r.text and "batch not eligible" in r.text
    assert (await run(db, uid, "search_posts", query="nonexistentco")).text.startswith("No saved posts mention")


async def test_chat_counts_jobs_not_posts(db, smtp):
    """'All posts today' when one post lists three jobs: the AI hears 3 jobs, one line each, never '1 post'."""
    uid, _ = await setup(db)
    ch = (await db.execute(select(Channel).where(Channel.user_id == uid))).scalars().first()
    p = Post(user_id=uid, channel_id=ch.id, tg_message_id=70, posted_at=NOW, stage="scored", text="1) A 2) B 3) C")
    db.add(p)
    await db.flush()
    db.add_all([Job(user_id=uid, post_id=p.id, idx=i, company=c, role="ML Engineer", fit_score=s, verdict=v,
                    apply_method="email") for i, (c, s, v) in enumerate([("Alpha", 85, "STRONG MATCH"),
                                                                         ("Beta", 30, "SKIP"), ("Gamma", 70, "APPLY")])])
    await db.commit()
    r = await run(db, uid, "list_posts", date=NOW.astimezone(report.IST).date().isoformat())
    assert all(f"ML Engineer · {c}" in r.text for c in ("Alpha", "Beta", "Gamma"))
    assert "jobs in" in r.text and "Talk about JOBS" in r.text
