"""Email accounts + sending settings API: fake SMTP, so no real email is ever sent here."""
from datetime import UTC, datetime, timedelta

import aiosmtplib
import pytest
from sqlalchemy import select

from app.db.models import SenderAccount, Send, User
from app.mailer import senders
from tests.conftest import requires_db
from tests.test_auth_api import PW, api, bearer, secrets  # noqa: F401 (fixtures)

pytestmark = requires_db


@pytest.fixture
def smtp(monkeypatch):
    """Records messages; the password 'wrong' is refused like Gmail does."""
    sent = []

    async def fake_send(message, **kw):
        if kw.get("password") == "wrong":
            raise aiosmtplib.SMTPAuthenticationError(535, "Username and Password not accepted")
        sent.append(message)

    monkeypatch.setattr(senders, "_smtp_send", fake_send)
    return sent


async def user(api, email="a@x.com"):
    return bearer((await api.post("/auth/signup", json={"email": email, "password": PW, "device_name": "t"})).json())


async def connect(api, h, email="me@gmail.com", password="abcd efgh ijkl mnop"):
    return await api.post("/senders", headers=h, json={"email": email, "password": password})


async def test_connect_checks_the_login_and_never_returns_the_password(api, db, smtp):
    h = await user(api)
    r = await connect(api, h)
    assert r.status_code == 200 and "abcd" not in r.text and "password_enc" not in r.text
    assert smtp[0]["To"] == "me@gmail.com" and smtp[0]["Subject"] == "Leapvoy is connected"
    listed = await api.get("/senders", headers=h)
    assert "abcd" not in listed.text and "password_enc" not in listed.text
    [acc] = listed.json()
    assert acc["email"] == "me@gmail.com" and acc["is_default"] and acc["daily_limit"] == 20
    assert acc["sent_today"] == 0 and acc["scheduled"] == 0 and "apppasswords" in acc["app_password_help"]


async def test_wrong_password_and_unknown_domain_are_explained(api, db, smtp):
    h = await user(api)
    r = await connect(api, h, password="wrong")
    assert r.status_code == 400 and "App Password" in r.json()["detail"]
    r = await connect(api, h, email="me@mycompany.dev")
    assert r.status_code == 400 and "Gmail, Outlook, Zoho or Yahoo" in r.json()["detail"]
    assert (await api.get("/senders", headers=h)).json() == []


async def test_default_limit_test_mail_and_remove(api, db, smtp):
    h = await user(api)
    a = (await connect(api, h, "a@gmail.com")).json()["id"]
    b = (await connect(api, h, "b@gmail.com")).json()["id"]
    assert (await api.post(f"/senders/{b}/default", headers=h)).status_code == 200
    rows = {x["email"]: x for x in (await api.get("/senders", headers=h)).json()}
    assert rows["b@gmail.com"]["is_default"] and not rows["a@gmail.com"]["is_default"]
    for bad in (0, 501):  # 500/day is Gmail's own ceiling for a personal account
        assert (await api.patch(f"/senders/{a}", headers=h, json={"daily_limit": bad})).status_code == 422
    assert (await api.patch(f"/senders/{a}", headers=h, json={"daily_limit": 60})).json()["daily_limit"] == 60
    assert (await api.patch(f"/senders/{a}", headers=h, json={"daily_limit": 5})).json()["daily_limit"] == 5
    assert (await api.post(f"/senders/{a}/test", headers=h)).status_code == 200
    assert smtp[-1]["To"] == "a@gmail.com" and smtp[-1]["Subject"] == "Leapvoy test email"
    assert (await api.delete(f"/senders/{b}", headers=h)).status_code == 204
    [left] = (await api.get("/senders", headers=h)).json()
    assert left["email"] == "a@gmail.com" and left["is_default"]  # the default moved


async def test_cannot_remove_an_account_a_scheduled_email_uses(api, db, smtp):
    from app.mailer import outbox
    from tests.test_outbox import setup

    uid, [job] = await setup(db, email="a@x.com")  # a job with a draft + me@gmail.com connected
    await outbox.approve(db, uid, job, datetime.now(UTC) + timedelta(hours=1))
    h = await user(api)  # signs up the same (CLI-made) account
    [acc] = (await api.get("/senders", headers=h)).json()
    assert acc["scheduled"] == 1
    r = await api.delete(f"/senders/{acc['id']}", headers=h)
    assert r.status_code == 409 and "scheduled" in r.json()["detail"]
    assert (await db.execute(select(Send).where(Send.user_id == uid))).scalar_one().status == "scheduled"


async def test_turning_test_mode_off_needs_a_sender_and_a_confirm(api, db, smtp):
    h = await user(api)
    s = (await api.get("/sending", headers=h)).json()
    assert s["test_mode"] is True and s["rules"] == {"daily_limit_default": 20, "daily_limit_max": 500, "gap_minutes": [3, 8],
                                                    "hr_cooldown_days": 30}
    r = await api.put("/sending", headers=h, json={"test_mode": False, "confirm": True})
    assert r.status_code == 400 and "Connect an email" in r.json()["detail"]
    await connect(api, h)
    r = await api.put("/sending", headers=h, json={"test_mode": False})
    assert r.status_code == 400 and "confirm" in r.json()["detail"].lower()
    assert (await api.put("/sending", headers=h, json={"test_mode": False, "confirm": True})).json()["test_mode"] is False
    assert (await api.put("/sending", headers=h, json={"test_mode": True})).json()["test_mode"] is True


async def test_other_users_cannot_touch_my_accounts(api, db, smtp):
    a = await user(api, "a@x.com")
    b = await user(api, "b@x.com")
    sid = (await connect(api, a)).json()["id"]
    assert (await api.get("/senders", headers=b)).json() == []
    for call in (api.post(f"/senders/{sid}/default", headers=b), api.post(f"/senders/{sid}/test", headers=b),
                 api.patch(f"/senders/{sid}", headers=b, json={"daily_limit": 3}), api.delete(f"/senders/{sid}", headers=b)):
        assert (await call).status_code == 404
    assert (await db.get(SenderAccount, sid)) is not None


async def test_emails_for_jobs_pasted_in_chat_count_toward_the_daily_limit(api, db, smtp):
    """A LinkedIn / Naukri post or screenshot pasted in chat is sent from the same account → same daily count."""
    from app.chat import tools
    from app.db.models import Channel, Draft, Job, Post, Resume
    from app.mailer import outbox
    from tests.test_outbox import NOW, setup

    uid, [tg_job] = await setup(db, email="a@x.com")  # a Telegram job with a draft, me@gmail.com connected
    resume = (await db.execute(select(Resume).where(Resume.user_id == uid))).scalar_one()
    ch = Channel(user_id=uid, tg_chat_id=0, title=tools.PASTED_CHANNEL, enabled=False)
    db.add(ch)
    await db.flush()
    pasted = []
    for i in range(2):
        post = Post(user_id=uid, channel_id=ch.id, tg_message_id=i + 1, text="LinkedIn post", posted_at=NOW, stage="scored")
        db.add(post)
        await db.flush()
        job = Job(user_id=uid, post_id=post.id, idx=0, company=f"Linked{i}", role="ML Engineer",
                  hr_emails=[f"hr@linked{i}.com"], fit_score=85, verdict="STRONG MATCH")
        db.add(job)
        await db.flush()
        db.add(Draft(user_id=uid, job_id=job.id, resume_id=resume.id, template_name="default-v1",
                     to_emails=[f"hr@linked{i}.com"], subject="s", body="b", status="draft"))
        pasted.append(job.id)
    acc = (await db.execute(select(SenderAccount).where(SenderAccount.user_id == uid))).scalar_one()
    acc.daily_limit = 2
    await db.commit()

    first = await outbox.approve(db, uid, pasted[0], NOW, now=NOW)  # pasted in chat
    second = await outbox.approve(db, uid, tg_job, NOW, now=NOW)  # from Telegram
    third = await outbox.approve(db, uid, pasted[1], NOW, now=NOW)  # pasted in chat, over the limit of 2
    ist = outbox.IST
    assert first.send_at.astimezone(ist).date() == second.send_at.astimezone(ist).date() == NOW.astimezone(ist).date()
    assert third.send_at.astimezone(ist).date() > NOW.astimezone(ist).date()  # pushed to the next day: all 3 counted
