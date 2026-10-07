from datetime import timedelta

import aiosmtplib
import pytest
from sqlalchemy import select

from app import notify
from app.db.models import Device, Job, Notification, Post
from app.mailer import outbox, senders
from tests.conftest import requires_db
from tests.test_auth_api import PW, api, bearer, secrets  # noqa: F401 (fixtures)
from tests.test_outbox import NOW, master_key, setup, smtp  # noqa: F401 (fixtures)

pytestmark = requires_db
TOKEN = "ExponentPushToken[abc]"
NIGHT = NOW.replace(hour=19)  # 00:30 India time (quiet hours)


@pytest.fixture
def expo(monkeypatch):
    box = {"sent": [], "dead": set()}

    async def fake(messages):
        box["sent"] += messages
        return [{"status": "error", "details": {"error": "DeviceNotRegistered"}} if m["to"] in box["dead"]
                else {"status": "ok", "id": "x"} for m in messages]

    monkeypatch.setattr(notify, "send_expo", fake)
    return box


async def phone(db, uid, token=TOKEN, name="Pixel"):
    d = Device(user_id=uid, name=name, refresh_hash=name * 8, push_token=token)
    db.add(d)
    await db.commit()
    return d


async def rows(db, uid, kind=None):
    q = select(Notification).where(Notification.user_id == uid)
    return (await db.execute(q.where(Notification.kind == kind) if kind else q)).scalars().all()


async def scored_jobs(db, uid, verdicts, posted=NOW):
    post = (await db.execute(select(Post).where(Post.user_id == uid))).scalars().first()
    post.posted_at = posted
    jobs = (await db.execute(select(Job).where(Job.user_id == uid))).scalars().all()
    for j, v in zip(jobs, verdicts):
        j.verdict, j.fit_score, j.apply_method, j.location = v, {"TOP PRIORITY": 92, "STRONG MATCH": 84}.get(v, 60), "email", "Pune"
    await db.commit()
    await notify.job_alerts(db, post, jobs, NOW)
    await db.commit()


async def test_good_fits_notify_and_several_become_one_push(db, smtp, expo):
    uid, _ = await setup(db, n_jobs=3)
    await phone(db, uid)
    await scored_jobs(db, uid, ["TOP PRIORITY", "STRONG MATCH", "SKIP"])
    alerts = await rows(db, uid, "job")
    assert len(alerts) == 2 and alerts[0].title.startswith(("92 · Excellent fit", "84 · Strong fit"))
    assert "Pune" in alerts[0].body and "Email ready" in alerts[0].body
    assert await notify.push_pending(db, NOW) == 1  # one 'N new jobs' message, not a buzz per job
    [m] = expo["sent"]
    assert m["title"] == "2 new jobs for you" and m["body"].startswith("Best: 92") and m["channelId"] == "jobs"
    assert await notify.push_pending(db, NOW) == 0  # never twice


async def test_old_posts_and_weaker_fits_do_not_buzz(db, smtp, expo):
    uid, _ = await setup(db, n_jobs=1)
    await scored_jobs(db, uid, ["STRONG MATCH"], posted=NOW - timedelta(days=5))  # a backfill being checked
    assert await rows(db, uid, "job") == []
    uid2, _ = await setup(db, email="b@x.com", n_jobs=1)
    await phone(db, uid2)
    await scored_jobs(db, uid2, ["APPLY"])  # Good fit, below the default 'Strong' buzz level
    [n] = await rows(db, uid2, "job")
    assert n.push == "none" and await notify.push_pending(db, NOW) == 0
    await notify.save_prefs(db, uid2, {"min_fit": "APPLY"})
    post2 = (await db.execute(select(Post).where(Post.user_id == uid2))).scalars().first()
    await notify.job_alerts(db, post2, (await db.execute(select(Job).where(Job.user_id == uid2))).scalars().all(), NOW)
    await db.commit()
    assert len(await rows(db, uid2, "job")) == 1  # one job never alerts twice (e.g. re-checked after a new resume)
    new = Job(user_id=uid2, post_id=post2.id, idx=9, company="New", role="ML Engineer", verdict="APPLY",
              fit_score=70, apply_method="email")
    db.add(new)
    await db.commit()
    await notify.job_alerts(db, post2, [new], NOW)
    await db.commit()
    assert await notify.push_pending(db, NOW) == 1  # a new Good fit buzzes now that the user asked for those


async def test_quiet_hours_hold_jobs_but_security_goes(db, smtp, expo):
    uid, _ = await setup(db, n_jobs=1)
    await phone(db, uid)
    await scored_jobs(db, uid, ["TOP PRIORITY"])
    await notify.add(db, uid, "new_device", "New sign-in on Laptop")
    await db.commit()
    assert await notify.push_pending(db, NIGHT) == 1 and expo["sent"][0]["channelId"] == "account"
    assert await notify.push_pending(db, NOW) == 1 and expo["sent"][1]["title"].startswith("92")  # morning


async def test_dead_token_is_dropped_and_no_phone_means_inbox_only(db, smtp, expo):
    uid, _ = await setup(db)
    d = await phone(db, uid)
    expo["dead"].add(TOKEN)
    await notify.add(db, uid, "reply", "NovaMind replied")
    await db.commit()
    await notify.push_pending(db, NOW)
    await db.refresh(d)
    assert d.push_token is None
    await notify.add(db, uid, "reply", "Kiwimesh replied")
    await db.commit()
    assert await notify.push_pending(db, NOW) == 0
    assert [n.push for n in await rows(db, uid, "reply")] == ["sent", "none"]


async def test_signed_out_phone_gets_nothing(db, smtp, expo):
    uid, _ = await setup(db)
    d = await phone(db, uid)
    d.revoked_at = NOW
    await notify.add(db, uid, "reply", "NovaMind replied")
    await db.commit()
    assert await notify.push_pending(db, NOW) == 0 and expo["sent"] == []


async def test_failed_send_and_daily_limit_notify_once(db, smtp, expo):
    uid, jobs = await setup(db, n_jobs=3)
    acc = await senders.default_sender(db, uid)
    acc.daily_limit = 1  # a failed mail doesn't use up the limit; the one sent after it does
    await db.commit()
    sends = [await outbox.approve(db, uid, j, NOW, now=NOW) for j in jobs]
    smtp["fail"] = aiosmtplib.SMTPAuthenticationError(535, "bad credentials")
    assert await outbox.deliver(db, sends[0].id, now=NOW) == "failed"
    [f] = await rows(db, uid, "send_failed")
    assert f.title.startswith("Couldn't send to") and f.data["screen"] == "senders"
    smtp["fail"] = None
    assert await outbox.deliver(db, sends[1].id, now=NOW + timedelta(minutes=10)) == "sent"
    for _ in range(2):
        await outbox.deliver(db, sends[2].id, now=NOW + timedelta(minutes=20))
    [lim] = await rows(db, uid, "limit")
    assert "Daily limit reached" in lim.title and "tomorrow" in lim.body


async def test_muted_kind_is_not_saved_but_security_cannot_be_muted(api, db, smtp):
    uid, _ = await setup(db)
    await notify.save_prefs(db, uid, {"off": ["reply"]})
    assert await notify.add(db, uid, "reply", "x") is None
    h = bearer((await api.post("/auth/signup", json={"email": "a@x.com", "password": PW, "device_name": "t"})).json())
    assert (await api.put("/notify-prefs", headers=h, json={"off": ["new_device"]})).status_code == 400
    r = await api.put("/notify-prefs", headers=h, json={"off": ["summary"], "min_fit": "APPLY", "quiet_from": 22})
    assert r.json()["min_fit"] == "APPLY" and r.json()["quiet_to"] == 8


async def test_inbox_token_and_sign_in_alert_per_user(api, db, smtp):
    await setup(db)
    a = bearer((await api.post("/auth/signup", json={"email": "a@x.com", "password": PW, "device_name": "Phone"})).json())
    assert (await api.post("/push-token", headers=a, json={"token": "nope"})).status_code == 400
    assert (await api.post("/push-token", headers=a, json={"token": TOKEN})).status_code == 200
    await api.post("/auth/login", json={"email": "a@x.com", "password": PW, "device_name": "Edge on Windows"})
    box = (await api.get("/notifications", headers=a)).json()
    assert box["unread"] == 1 and box["items"][0]["title"] == "New sign-in on Edge on Windows"
    b = bearer((await api.post("/auth/signup", json={"email": "b@x.com", "password": PW, "device_name": "Phone"})).json())
    assert (await api.get("/notifications", headers=b)).json() == {"unread": 0, "items": []}  # isolation
    await api.post("/push-token", headers=b, json={"token": TOKEN})  # same phone, other account: token moves
    tokens = (await db.execute(select(Device.push_token).where(Device.push_token.is_not(None)))).scalars().all()
    assert tokens == [TOKEN]
    await api.post("/notifications/read", headers=b, json={})
    assert (await api.get("/notifications", headers=a)).json()["unread"] == 1  # b can't mark a's
    await api.post("/notifications/read", headers=a, json={})
    assert (await api.get("/notifications", headers=a)).json()["unread"] == 0


async def test_morning_summary_once_a_day(db, smtp, expo):
    uid, _ = await setup(db)
    await notify.add(db, uid, "reply", "warm-up")  # any row; the summary counts yesterday's posts
    post = (await db.execute(select(Post).where(Post.user_id == uid))).scalars().first()
    post.posted_at = NOW - timedelta(days=1)
    from app.db.models import User
    (await db.get(User, uid)).password_hash = "x"  # a signed-up account
    await db.commit()
    assert await notify.morning_summary(db, NOW.replace(hour=1)) == 0  # 6:30 AM India: too early
    assert await notify.morning_summary(db, NOW) == 1
    assert await notify.morning_summary(db, NOW + timedelta(hours=2)) == 0
    [s] = await rows(db, uid, "summary")
    assert s.title.startswith("Yesterday: 1 posts")
