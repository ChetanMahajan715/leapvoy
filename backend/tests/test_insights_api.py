"""Templates preview (exactly the real template, parts labelled) + stats (real numbers, test mode kept apart)."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.chat import tools
from app.db.models import Job, Post, Send, User
from app.mailer import outbox
from app.mailer.render import default_template, render
from tests.conftest import requires_db
from tests.test_auth_api import PW, api, bearer, secrets  # noqa: F401 (fixtures)
from tests.test_outbox import setup, smtp  # noqa: F401 (fixtures)

pytestmark = requires_db
PROFILE = {"full_name": "Chetan Mahajan", "phone": "9000000000", "linkedin_url": "https://linkedin.com/in/c",
           "github_url": "https://github.com/c"}


async def signin(api, email="a@x.com"):
    return bearer((await api.post("/auth/signup", json={"email": email, "password": PW, "device_name": "t"})).json())


async def test_template_preview_is_the_real_template_with_labelled_parts(api, db):
    h = await signin(api)
    await api.put("/profile", headers=h, json=PROFILE)
    t = (await api.get("/template", headers=h)).json()
    kinds = {p["kind"] for p in t["body"]}
    assert kinds == {"fixed", "profile", "job", "ai"} and t["name"] == "default-v1"
    text = "".join(p["text"] for p in t["body"])
    subject = "".join(p["text"] for p in t["subject"])
    # the same text the real renderer gives, AI slots aside
    ai = {p["text"] for p in t["body"] if p["kind"] == "ai"}
    want_subject, want_body = render(default_template(), role="AI Engineer", company="Acme Technologies",
                                     hr_first_name=None, subject_override=None, subject_extras="", profile=PROFILE,
                                     opening_line="§O", closing_line="§C",
                                     fit_bullets=[{"label": "§L", "proof": "§P"}] * 3)
    assert subject == want_subject and "Dear Hiring Team," in text and "Best regards,\nChetan Mahajan\n9000000000" in text
    assert len(ai) >= 3 and all("AI" in a or "resume" in a.lower() for a in ai)
    assert any(p["kind"] == "profile" and p["text"] == "https://github.com/c" for p in t["body"])


async def test_template_preview_for_one_of_my_jobs_and_not_others(api, db, smtp):
    uid, [job] = await setup(db, email="a@x.com")
    h = await signin(api)
    await api.put("/profile", headers=h, json=PROFILE)
    t = (await api.get("/template", headers=h, params={"job_id": job})).json()
    assert "Company0" in "".join(p["text"] for p in t["body"])
    other = await signin(api, "b@x.com")
    assert (await api.get("/template", headers=other, params={"job_id": job})).status_code == 404


async def test_stats_count_the_funnel_and_keep_test_mode_apart(api, db, smtp):
    uid, jobs = await setup(db, email="a@x.com", n_jobs=3)  # 1 post (scored) with 3 STRONG MATCH jobs, at 30 Sep
    now = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)
    j = await db.get(Job, jobs[2])
    j.verdict = "SKIP"
    await db.commit()
    test_send = await outbox.approve(db, uid, jobs[0], now, now=now)  # test mode is on by default
    await outbox.set_test_mode(db, uid, False)
    real = await outbox.approve(db, uid, jobs[1], now, now=now)
    for snd, replied in ((test_send, False), (real, True)):
        row = await db.get(Send, snd.id)
        row.status, row.sent_at = "sent", now
        if replied:
            row.replied_at = now + timedelta(hours=2)
    await db.commit()
    from app.api.stats import compute
    st = await compute(db, uid, 7, now=now)
    assert st["funnel"] == {"posts": 1, "checked": 1, "fit": 2, "sent": 1, "replies": 1, "reply_rate": 100}
    assert st["fit_breakdown"] == {"Excellent fit": 0, "Strong fit": 2, "Good fit": 0, "Possible fit": 0}
    assert st["test_sent"] == 1 and st["senders"] == [{"email": "me@gmail.com", "sent": 1, "replies": 1, "reply_rate": 100}]
    assert len(st["days"]) == 7 and st["days"][-1]["date"] == "2026-10-02" and st["days"][-1]["sent"] == 1
    assert sum(d["posts"] for d in st["days"]) == 1
    # the chat answers with the same numbers
    r = await tools.run_tool(db, uid, "stats", {"days": 7}, tools.Context(now=now, incognito=False, last_user_message=""))
    assert "1 post" in r.text and "1 email" in r.text and "1 repl" in r.text
    # other users see nothing of it
    h = await signin(api, "b@x.com")
    b = (await api.get("/stats", headers=h, params={"days": 30})).json()
    assert b["funnel"]["posts"] == 0 and b["funnel"]["sent"] == 0 and b["senders"] == []
    assert (await api.get("/stats", headers=h, params={"days": 5})).status_code == 422


async def test_stats_for_one_day(api, db, smtp):
    from app.api.stats import compute
    uid, _ = await setup(db, email="a@x.com")  # one post on 30 Sep (IST)
    from datetime import date
    on = await compute(db, uid, day=date(2026, 9, 30), now=datetime(2026, 10, 2, 6, 0, tzinfo=UTC))
    off = await compute(db, uid, day=date(2026, 10, 1), now=datetime(2026, 10, 2, 6, 0, tzinfo=UTC))
    assert on["funnel"]["posts"] == 1 and on["from"] == on["to"] == "2026-09-30" and len(on["days"]) == 1
    assert off["funnel"]["posts"] == 0
    h = await signin(api)
    assert (await api.get("/stats", headers=h, params={"date": "2026-09-30"})).json()["funnel"]["posts"] == 1
    assert (await api.get("/stats", headers=h, params={"date": "someday"})).status_code == 422


async def test_template_editor_api(api, db):
    h = await signin(api)
    await api.put("/profile", headers=h, json=PROFILE)
    e = (await api.get("/templates", headers=h)).json()
    assert e["active"] == "default-v1" and e["text"] == e["default_text"] and e["versions"] == []
    assert {t["tag"] for t in e["tags"] if t["ai"]} == {"{opening_line}", "{fit_bullets}", "{closing_line}"}
    text = e["text"].replace("Best regards,", "Warm regards,")
    p = (await api.post("/templates/preview", headers=h, json={"text": text})).json()
    assert "Warm regards," in "".join(x["text"] for x in p["body"])
    bad = await api.post("/templates/preview", headers=h, json={"text": text.replace("{fit_bullets}", "")})
    assert bad.status_code == 422 and "{fit_bullets}" in bad.json()["detail"]
    saved = (await api.post("/templates", headers=h, json={"text": text})).json()
    assert saved["active"] == "custom-v1" and saved["versions"][0]["is_active"]
    assert (await api.get("/template", headers=h)).json()["name"] == "custom-v1"
    assert (await api.post("/templates/default", headers=h)).json()["active"] == "default-v1"
    vid = saved["versions"][0]["id"]
    other = await signin(api, "b@x.com")
    assert (await api.post(f"/templates/{vid}/activate", headers=other)).status_code == 404
    assert (await api.post(f"/templates/{vid}/activate", headers=h)).json()["active"] == "custom-v1"
