from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.chat import tools
from app.db.models import Draft, Job, Send
from app.telegram.store import save_session
from tests.conftest import requires_db
from tests.test_auth_api import PW, api, bearer, secrets  # noqa: F401 (fixtures)
from tests.test_outbox import NOW, setup, smtp  # noqa: F401 (fixtures)

pytestmark = requires_db


async def signed_in(api, db, **kw):
    """Data made by the test helper, then the account claimed through the real sign-up API."""
    uid, jobs = await setup(db, **kw)
    r = await api.post("/auth/signup", json={"email": kw.get("email", "a@x.com"), "password": PW, "device_name": "t"})
    return uid, jobs, bearer(r.json())


async def test_job_details_include_draft_and_send_status(api, db, smtp):
    uid, [job], h = await signed_in(api, db)
    j = (await api.get(f"/jobs/{job}", headers=h)).json()
    assert (j["company"], j["verdict"], j["apply_method"]) == ("Company0", "STRONG MATCH", "email")
    assert j["draft"]["status"] == "draft" and j["draft"]["outdated"] is False and j["send"] is None


async def test_jobs_by_ids_for_chat_cards(api, db, smtp):
    uid, jobs, h = await signed_in(api, db, n_jobs=2)
    r = await api.get(f"/jobs?ids={jobs[1]},{jobs[0]}", headers=h)
    assert [j["id"] for j in r.json()] == [jobs[1], jobs[0]]


async def test_card_button_schedules_then_shows_live_status(api, db, smtp):
    uid, [job], h = await signed_in(api, db)
    r = await api.post(f"/jobs/{job}/schedule", headers=h, json={"when": "tomorrow 10am"})
    assert r.status_code == 200 and r.json()["status"] == "scheduled" and r.json()["test_mode"] is True
    assert (await api.get(f"/jobs/{job}", headers=h)).json()["send"]["status"] == "scheduled"


async def test_bad_time_or_blocked_send_gives_a_clear_error(api, db, smtp):
    uid, [job], h = await signed_in(api, db, draft_status="needs_review")
    r = await api.post(f"/jobs/{job}/schedule", headers=h, json={"when": "now"})
    assert r.status_code == 400 and "review" in r.json()["detail"]
    r = await api.post(f"/jobs/{job}/schedule", headers=h, json={"when": "whenever"})
    assert r.status_code == 400


async def test_confirm_card_via_api(api, db, smtp):
    uid, [job], h = await signed_in(api, db)
    proposal = await tools.run_tool(db, uid, "schedule_email", {"job_id": job, "when": "now"},
                                    tools.Context(now=NOW, incognito=False, last_user_message=""))
    aid = proposal.card["action_id"]
    assert (await api.get(f"/actions/{aid}", headers=h)).json()["status"] == "pending"
    r = await api.post(f"/actions/{aid}/confirm", headers=h)
    assert r.json()["status"] == "done"
    assert (await api.post(f"/actions/{aid}/confirm", headers=h)).status_code == 409


async def test_scheduled_list_cancel_and_move(api, db, smtp):
    uid, [job], h = await signed_in(api, db)
    await api.post(f"/jobs/{job}/schedule", headers=h, json={"when": "tomorrow 10am"})
    [s] = (await api.get("/sends?status=scheduled", headers=h)).json()
    assert s["company"] == "Company0"
    moved = await api.post(f"/sends/{s['id']}/reschedule", headers=h, json={"when": "monday 11am"})
    assert moved.status_code == 200 and moved.json()["send_at"] != s["send_at"]
    assert (await api.post(f"/sends/{s['id']}/cancel", headers=h)).status_code == 200
    assert (await api.get("/sends?status=scheduled", headers=h)).json() == []


async def test_other_users_jobs_sends_and_actions_are_404(api, db, smtp):
    uid, [job], h = await signed_in(api, db)
    await api.post(f"/jobs/{job}/schedule", headers=h, json={"when": "tomorrow 10am"})
    send_id = (await db.execute(select(Send.id))).scalar_one()
    other = bearer((await api.post("/auth/signup", json={"email": "b@x.com", "password": PW, "device_name": "t"})).json())
    assert (await api.get(f"/jobs/{job}", headers=other)).status_code == 404
    assert (await api.get(f"/jobs?ids={job}", headers=other)).json() == []
    assert (await api.post(f"/jobs/{job}/schedule", headers=other, json={"when": "now"})).status_code == 404
    assert (await api.post(f"/sends/{send_id}/cancel", headers=other)).status_code == 404
    assert (await api.get("/sends?status=scheduled", headers=other)).json() == []


@pytest.mark.parametrize("path", ["/jobs/1", "/jobs?ids=1", "/sends", "/actions/1"])
async def test_needs_sign_in(api, path):
    assert (await api.get(path)).status_code == 401


async def test_job_card_has_the_post_fields_and_the_original_post(api, db, smtp):
    uid, [job], h = await signed_in(api, db)
    j = await db.get(Job, job)
    j.must_have_skills, j.apply_instructions, j.salary = ["Python", "LLMs"], 'Subject: "AI Engineer - Fresher"', "₹30k/month"
    await db.commit()
    got = (await api.get(f"/jobs/{job}", headers=h)).json()
    assert got["must_have_skills"] == ["Python", "LLMs"] and got["salary"] == "₹30k/month"
    assert got["apply_instructions"].startswith("Subject") and got["post_text"] == "post"  # the Telegram text as-is


async def test_schedule_to_chosen_hr_addresses(api, db, smtp):
    uid, [job], h = await signed_in(api, db)
    two = ["hr@acme.com", "talent@acme.com"]
    (await db.get(Job, job)).hr_emails = two
    (await db.execute(select(Draft).where(Draft.job_id == job))).scalar_one().to_emails = two
    await db.commit()
    r = await api.post(f"/jobs/{job}/schedule", headers=h, json={"when": "tomorrow 10am", "to": two})
    assert r.status_code == 200 and r.json()["to_emails"] == two
    r = await api.get("/sends?status=scheduled", headers=h)
    assert r.json()[0]["to_emails"] == two


async def test_chat_proposal_sends_to_every_hr_address(api, db, smtp):
    uid, [job], h = await signed_in(api, db)
    two = ["hr@acme.com", "talent@acme.com"]
    (await db.execute(select(Draft).where(Draft.job_id == job))).scalar_one().to_emails = two
    (await db.get(Job, job)).hr_emails = two
    await db.commit()
    p = await tools.run_tool(db, uid, "schedule_email", {"job_id": job, "when": "now"},
                             tools.Context(now=NOW, incognito=False, last_user_message=""))
    a = (await api.get(f"/actions/{p.card['action_id']}", headers=h)).json()
    assert "hr@acme.com, talent@acme.com" in a["summary"]
    assert (await api.post(f"/actions/{a['id']}/confirm", headers=h)).status_code == 200
    assert (await db.execute(select(Send.to_emails))).scalar_one() == two


async def test_new_good_jobs_since_last_look_for_the_badge(api, db, smtp):
    uid, jobs, h = await signed_in(api, db, n_jobs=2)
    skip = await db.get(Job, jobs[1])
    skip.verdict = "SKIP"  # not worth a notification
    await db.commit()
    r = (await api.get("/jobs/new", headers=h, params={"since": "2000-01-01T00:00:00Z"})).json()
    assert r["count"] == 1 and r["jobs"][0]["id"] == jobs[0] and r["jobs"][0]["company"] == "Company0"
    later = (await api.get("/jobs/new", headers=h, params={"since": "2999-01-01T00:00:00Z"})).json()
    assert later == {"count": 0, "jobs": []}


async def test_write_email_with_a_chosen_model(api, db, smtp, monkeypatch):
    uid, [job], h = await signed_in(api, db)
    used = []

    async def fake_write(s, user_id, job_id, model=None):
        used.append(model)

    monkeypatch.setattr("app.api.jobs.drafts.write_draft", fake_write)
    r = await api.post(f"/jobs/{job}/draft", headers=h, json={"model": "groq/openai/gpt-oss-120b"})
    assert r.status_code == 200 and used == ["groq/openai/gpt-oss-120b"]
    assert (await api.post(f"/jobs/{job}/draft", headers=h)).status_code == 200 and used[-1] is None  # Auto
    assert (await api.post(f"/jobs/{job}/draft", headers=h, json={"model": "x/nope"})).status_code == 400


async def test_fetch_button_reads_only_new_posts_and_checks_only_unprocessed(api, db, smtp, monkeypatch):
    from tests.test_chat_tools import _noop

    uid, _, h = await signed_in(api, db)
    await save_session(db, uid, "+910000000000", "session-string")
    checked = []

    async def fake_connect(session_str):
        return SimpleNamespace(disconnect=_noop)

    async def fake_catch_up(client, sm, user_id):
        return 4  # 4 posts Leapvoy didn't have yet

    async def fake_next(s, user_id, limit, since=None, until=None):
        return [11, 12]  # not processed yet (already-processed ones are never picked)

    async def fake_run_post(sm, post_id):
        checked.append(post_id)
        return "scored"

    monkeypatch.setattr(tools.reader, "connect", fake_connect)
    monkeypatch.setattr(tools.reader, "catch_up", fake_catch_up)
    monkeypatch.setattr(tools.pipeline_store, "next_posts", fake_next)
    monkeypatch.setattr(tools.graph, "run_post", fake_run_post)
    r = await api.post("/jobs/fetch", headers=h, json={"date": "2026-09-30"})
    assert r.status_code == 200 and r.json() == {"new_posts": 4, "checked": 2, "waiting": 0, "paused": False, "problem": None}
    assert checked == [11, 12]


async def test_fetch_without_telegram_says_so(api, db, smtp):
    uid, _, h = await signed_in(api, db)
    r = (await api.post("/jobs/fetch", headers=h, json={"date": "today"})).json()
    assert r["problem"].startswith("Telegram isn't connected")


async def test_search_sent_and_scheduled_emails(api, db, smtp):
    """Find when you emailed a company: by company, role, subject or HR address; every word must match."""
    from datetime import timedelta

    from app.mailer import outbox
    uid, jobs = await setup(db, n_jobs=3)  # Company0..2, hr0@company0.com..
    j = await db.get(Job, jobs[1])
    j.company, j.role = "Blinkit", "Associate Program Manager"
    await db.commit()
    for job in jobs:
        await outbox.approve(db, uid, job, NOW + timedelta(hours=1), now=NOW)
    h = bearer((await api.post("/auth/signup", json={"email": "a@x.com", "password": PW, "device_name": "t"})).json())

    async def find(q, **kw):
        return [x["company"] for x in (await api.get("/sends", headers=h, params={"q": q, **kw})).json()]

    assert await find("blinkit") == ["Blinkit"]
    assert await find("BLINKIT program") == ["Blinkit"]
    assert await find("blinkit intern") == []  # every word must match
    assert await find("hr2@company2") == ["Company2"]  # by HR address
    assert await find("blinkit", status="scheduled") == ["Blinkit"]
    assert len(await find("")) == 3
    other = bearer((await api.post("/auth/signup", json={"email": "b@x.com", "password": PW, "device_name": "t"})).json())
    assert (await api.get("/sends", headers=other, params={"q": "blinkit"})).json() == []
