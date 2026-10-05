"""Change password, delete account (7-day grace, explicit restore, then everything gone), and the 30-day cleanup
of old posts that keeps what you applied to and keeps stats right."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.accounts import deletion
from app.api.stats import compute
from app.db.models import DayStats, Device, Job, Post, SenderAccount, Send, User
from app.mailer import outbox
from app.pipeline import retention
from app.pipeline import store as pipeline_store
from app.telegram import store as tg_store
from tests.conftest import requires_db
from tests.test_auth_api import PW, api, bearer, secrets  # noqa: F401 (fixtures)
from tests.test_outbox import NOW, setup, smtp  # noqa: F401 (fixtures)

pytestmark = requires_db
NEW = "a brand new passphrase"


async def signup(api, email="a@x.com", device="Phone"):
    r = await api.post("/auth/signup", json={"email": email, "password": PW, "device_name": device})
    return r.json()


# --- change password ----------------------------------------------------------------------

async def test_change_password_needs_the_current_one_and_signs_out_other_devices(api, db):
    phone = await signup(api)
    laptop = (await api.post("/auth/login", json={"email": "a@x.com", "password": PW, "device_name": "Laptop"})).json()
    h = bearer(phone)
    r = await api.post("/auth/password/change", headers=h, json={"current_password": "wrong one!!", "new_password": NEW})
    assert r.status_code == 401
    r = await api.post("/auth/password/change", headers=h, json={"current_password": PW, "new_password": PW})
    assert r.status_code == 400 and "different" in r.json()["detail"]
    r = await api.post("/auth/password/change", headers=h, json={"current_password": PW, "new_password": NEW})
    assert r.status_code == 200
    assert (await api.get("/me", headers=h)).status_code == 200  # this device stays signed in
    assert (await api.get("/me", headers=bearer(laptop))).status_code == 401  # the other one is signed out
    assert (await api.post("/auth/login", json={"email": "a@x.com", "password": PW, "device_name": "x"})).status_code == 401
    assert (await api.post("/auth/login", json={"email": "a@x.com", "password": NEW, "device_name": "x"})).status_code == 200


async def test_change_password_asks_for_the_2fa_code_when_it_is_on(api, db):
    import pyotp

    from app.accounts import auth
    h = bearer(await signup(api))
    secret = (await api.post("/auth/2fa/setup", headers=h)).json()["totp_secret"]
    await api.post("/auth/2fa/enable", headers=h, json={"code": pyotp.TOTP(secret).now()})
    body = {"current_password": PW, "new_password": NEW}
    assert (await api.post("/auth/password/change", headers=h, json=body)).status_code == 401
    r = await api.post("/auth/password/change", headers=h, json={**body, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200
    user = (await db.execute(select(User).where(User.email == "a@x.com"))).scalar_one()
    await db.refresh(user)
    assert auth.password_ok(user, NEW)


# --- delete account -------------------------------------------------------------------------

async def test_delete_account_stops_everything_then_restore_or_purge(api, db, smtp, monkeypatch):
    uid, [job] = await setup(db, email="a@x.com")  # a job, a draft, a connected Gmail
    await outbox.approve(db, uid, job, NOW + timedelta(days=1), now=NOW)  # a scheduled email
    await tg_store.save_session(db, uid, "+919876543210", "tg-session")
    tokens = await signup(api)
    h = bearer(tokens)
    bad = await api.post("/auth/account/delete", headers=h, json={"password": PW, "confirm": "delete me"})
    assert bad.status_code == 422
    assert (await api.post("/auth/account/delete", headers=h,
                           json={"password": "wrong pass!!", "confirm": "DELETE"})).status_code == 401
    r = await api.post("/auth/account/delete", headers=h, json={"password": PW, "confirm": "DELETE"})
    assert r.status_code == 200 and r.json()["delete_after"]
    assert (await api.get("/me", headers=h)).status_code == 401  # every device signed out
    send = (await db.execute(select(Send).where(Send.user_id == uid))).scalar_one()
    await db.refresh(send)
    assert send.status == "cancelled"
    assert uid not in await tg_store.users_with_telegram(db)  # Telegram reading stops
    db.add(Post(user_id=uid, channel_id=(await db.get(Post, (await db.get(Job, job)).post_id)).channel_id,
                tg_message_id=99, text="new", posted_at=NOW, stage="new"))
    await db.commit()
    assert uid not in await pipeline_store.users_with_pending(db)  # no AI work for it

    # sign in during the 7 days: the app shows "Keep my account" (nothing restores by itself)
    again = bearer((await api.post("/auth/login", json={"email": "a@x.com", "password": PW, "device_name": "x"})).json())
    assert (await api.get("/me", headers=again)).json()["delete_after"]
    assert (await api.post("/auth/account/restore", headers=again)).json()["delete_after"] is None
    assert uid in await tg_store.users_with_telegram(db)

    # delete again, and 7 days later it is gone completely (Telegram logged out too)
    await api.post("/auth/account/delete", headers=again, json={"password": PW, "confirm": "DELETE"})
    logged_out = []

    async def fake_logout(session_str):
        logged_out.append(session_str)

    monkeypatch.setattr(deletion, "telegram_log_out", fake_logout)
    assert await deletion.purge_due(db, datetime.now(UTC) + timedelta(days=6)) == 0
    assert await deletion.purge_due(db, datetime.now(UTC) + timedelta(days=7, minutes=1)) == 1
    assert logged_out == ["tg-session"]
    assert await db.scalar(select(func.count()).select_from(User).where(User.email == "a@x.com")) == 0
    for table in (Post, Job, Send, Device):
        assert await db.scalar(select(func.count()).select_from(table).where(table.user_id == uid)) == 0


# --- 30-day cleanup -------------------------------------------------------------------------

async def test_old_unused_posts_go_but_applied_ones_and_stats_stay(db, smtp):
    uid, jobs = await setup(db, email="a@x.com", n_jobs=2)  # one post (30 Sep) with 2 jobs
    ch = (await db.get(Post, (await db.get(Job, jobs[0])).post_id)).channel_id
    old = NOW - timedelta(days=40)
    for i in range(3):  # three old skipped posts
        db.add(Post(user_id=uid, channel_id=ch, tg_message_id=100 + i, text=f"old {i}", posted_at=old, stage="skipped",
                    skip_reason="low_match"))
    applied_post = Post(user_id=uid, channel_id=ch, tg_message_id=200, text="old applied", posted_at=old, stage="scored")
    db.add(applied_post)
    await db.flush()
    applied_job = Job(user_id=uid, post_id=applied_post.id, idx=0, company="Kept", role="AI Engineer",
                      hr_emails=["hr@kept.com"], fit_score=90, verdict="TOP PRIORITY")
    db.add(applied_job)
    await db.flush()
    sender_id = (await db.execute(select(SenderAccount.id).where(SenderAccount.user_id == uid))).scalar_one()
    db.add(Send(user_id=uid, job_id=applied_job.id, sender_id=sender_id, to_email="hr@kept.com", to_emails=["hr@kept.com"], send_key="old-1", send_at=old, sent_at=old,
        status="sent", test_mode=False, subject="s", body="b"))
    await db.commit()
    now = NOW + timedelta(days=1)
    before = await compute(db, uid, 90, now=now)

    removed = await retention.purge_old(db, now)
    assert removed == 3
    assert await db.scalar(select(func.count()).select_from(Post).where(Post.user_id == uid, Post.posted_at < now - timedelta(days=30))) == 1
    assert await db.get(Job, applied_job.id) is not None  # what you applied to stays
    assert await db.scalar(select(func.count()).select_from(DayStats).where(DayStats.user_id == uid)) == 1

    after = await compute(db, uid, 90, now=now)
    assert after["funnel"] == before["funnel"] and after["fit_breakdown"] == before["fit_breakdown"]
    assert [d["posts"] for d in after["days"]] == [d["posts"] for d in before["days"]]
    assert await retention.purge_old(db, now) == 0  # nothing left to do, no double counting
    assert (await compute(db, uid, 90, now=now))["funnel"] == before["funnel"]
