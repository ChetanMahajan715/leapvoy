import base64
import os
import random
from datetime import UTC, datetime, timedelta

import aiosmtplib
import pytest
from sqlalchemy import select

from app.accounts import profile
from app.core.config import get_settings
from app.db.models import Channel, DoNotContact, Draft, Job, Post, Resume, Send
from app.mailer import outbox, senders
from app.pipeline.report import IST
from app.telegram import store
from tests.conftest import requires_db

pytestmark = requires_db
NOW = datetime(2026, 9, 30, 4, 0, tzinfo=UTC)  # Wed 30 Sep, 9:30 AM IST
PDF = b"%PDF-1.4 resume"


@pytest.fixture(autouse=True)
def master_key(monkeypatch):
    monkeypatch.setenv("MASTER_KEY", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://unused/x")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def smtp(monkeypatch):
    box = {"sent": [], "fail": None}

    async def fake_send(message, **kw):
        if box["fail"]:
            raise box["fail"]
        box["sent"].append(message)

    monkeypatch.setattr(senders, "_smtp_send", fake_send)
    monkeypatch.setattr(outbox, "_rng", random.Random(7))
    return box


async def setup(db, email="a@x.com", n_jobs=1, hr=None, company=None, draft_status="draft"):
    uid = await store.get_or_create_user(db, email)
    await profile.set_profile(db, uid, {"full_name": "Chetan Mahajan"})
    resume = Resume(user_id=uid, name="AI", text="resume", pdf=PDF, filename="Chetan Mahajan Resume.pdf", is_active=True)
    ch = Channel(user_id=uid, tg_chat_id=-1001, title="Jobs", enabled=True)
    db.add_all([resume, ch])
    await db.flush()
    post = Post(user_id=uid, channel_id=ch.id, tg_message_id=1, text="post", posted_at=NOW, stage="scored")
    db.add(post)
    await db.flush()
    ids = []
    for i in range(n_jobs):
        to = hr or f"hr{i}@company{i}.com"
        job = Job(user_id=uid, post_id=post.id, idx=i, company=company or f"Company{i}", role="AI Engineer",
                  hr_emails=[to], fit_score=80, verdict="STRONG MATCH")
        db.add(job)
        await db.flush()
        db.add(Draft(user_id=uid, job_id=job.id, resume_id=resume.id, template_name="default-v1", to_emails=[to],
                     subject="Application for AI Engineer - Chetan Mahajan", body="Dear Hiring Team,\n\nHello.",
                     status=draft_status))
        ids.append(job.id)
    await db.commit()
    await senders.add_sender(db, uid, "me@gmail.com", "app pass word")
    return uid, ids


async def go_live(db, uid):
    await outbox.set_test_mode(db, uid, False)


# --- test mode ------------------------------------------------------------------

async def test_test_mode_is_on_and_mail_goes_to_own_inbox(db, smtp):
    uid, [job] = await setup(db)
    smtp["sent"].clear()  # drop the sender login test mail
    s = await outbox.approve(db, uid, job, NOW, now=NOW)
    assert s.test_mode and s.to_email == "hr0@company0.com" and s.subject.startswith("[TEST] ")
    assert await outbox.deliver(db, s.id, now=NOW) == "sent"
    [msg] = smtp["sent"]
    assert msg["To"] == "me@gmail.com"  # redirected to the user, never the HR
    assert "would have gone to: hr0@company0.com" in msg.get_body().get_content()
    [att] = list(msg.iter_attachments())
    assert att.get_filename() == "Chetan Mahajan Resume.pdf" and att.get_content() == PDF


async def test_live_mode_goes_to_hr(db, smtp):
    uid, [job] = await setup(db)
    await go_live(db, uid)
    smtp["sent"].clear()
    s = await outbox.approve(db, uid, job, NOW, now=NOW)
    await outbox.deliver(db, s.id, now=NOW)
    assert smtp["sent"][0]["To"] == "hr0@company0.com" and not s.subject.startswith("[TEST]")


# --- what can be approved --------------------------------------------------------

async def test_needs_review_draft_cannot_be_approved(db, smtp):
    uid, [job] = await setup(db, draft_status="needs_review")
    with pytest.raises(outbox.NotAllowed, match="review"):
        await outbox.approve(db, uid, job, NOW, now=NOW)


async def test_outdated_draft_cannot_be_approved(db, smtp):
    uid, [job] = await setup(db)
    for r in (await db.execute(select(Resume))).scalars():
        r.is_active = False
    db.add(Resume(user_id=uid, name="v2", text="new", pdf=PDF, is_active=True))
    await db.commit()
    with pytest.raises(outbox.NotAllowed, match="older resume"):
        await outbox.approve(db, uid, job, NOW, now=NOW)


async def test_same_job_cannot_be_scheduled_twice(db, smtp):
    uid, [job] = await setup(db)
    await outbox.approve(db, uid, job, NOW, now=NOW)
    with pytest.raises(outbox.NotAllowed, match="already"):
        await outbox.approve(db, uid, job, NOW, now=NOW)


async def test_cannot_approve_another_users_job(db, smtp):
    _, [job] = await setup(db, "a@x.com")
    other = await store.get_or_create_user(db, "b@x.com")
    with pytest.raises(outbox.JobNotFound):
        await outbox.approve(db, other, job, NOW, now=NOW)


# --- safety rules (live mode) ----------------------------------------------------

async def test_same_hr_only_once_in_30_days(db, smtp):
    uid, [a, b] = await setup(db, n_jobs=2, hr="hr@same.com")
    await go_live(db, uid)
    await outbox.approve(db, uid, a, NOW, now=NOW)
    with pytest.raises(outbox.NotAllowed, match="30 days"):
        await outbox.approve(db, uid, b, NOW, now=NOW)


async def test_same_company_and_role_only_once(db, smtp):
    uid, [a, b] = await setup(db, n_jobs=2, company="Acme")
    await go_live(db, uid)
    await outbox.approve(db, uid, a, NOW, now=NOW)
    with pytest.raises(outbox.NotAllowed, match="Acme"):
        await outbox.approve(db, uid, b, NOW, now=NOW)


async def test_do_not_contact_is_respected(db, smtp):
    uid, [job] = await setup(db)
    await go_live(db, uid)
    db.add(DoNotContact(user_id=uid, email="hr0@company0.com", reason="not interested"))
    await db.commit()
    with pytest.raises(outbox.NotAllowed, match="do-not-contact"):
        await outbox.approve(db, uid, job, NOW, now=NOW)


async def test_test_sends_do_not_block_real_ones(db, smtp):
    uid, [job] = await setup(db)
    await outbox.approve(db, uid, job, NOW, now=NOW)  # test mode
    await go_live(db, uid)
    assert not (await outbox.approve(db, uid, job, NOW, now=NOW)).test_mode


# --- pacing ------------------------------------------------------------------------

async def test_emails_are_spaced_3_to_8_minutes(db, smtp):
    uid, jobs = await setup(db, n_jobs=3)
    times = sorted([(await outbox.approve(db, uid, j, NOW, now=NOW)).send_at for j in jobs])
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:], strict=False)]
    assert all(180 <= g <= 480 for g in gaps)


async def test_daily_limit_moves_extra_mail_to_next_morning(db, smtp):
    uid, jobs = await setup(db, n_jobs=3)
    acc = await senders.default_sender(db, uid)
    acc.daily_limit = 2
    await db.commit()
    last = [await outbox.approve(db, uid, j, NOW, now=NOW) for j in jobs][-1]
    assert last.send_at.astimezone(IST).date() == NOW.astimezone(IST).date() + timedelta(days=1)
    assert last.send_at.astimezone(IST).hour == 10


# --- delivery safety ---------------------------------------------------------------

async def test_delivering_twice_sends_once(db, smtp):
    uid, [job] = await setup(db)
    smtp["sent"].clear()
    s = await outbox.approve(db, uid, job, NOW, now=NOW)
    await outbox.deliver(db, s.id, now=NOW)
    assert await outbox.deliver(db, s.id, now=NOW) == "skipped"
    assert len(smtp["sent"]) == 1


async def test_not_due_yet_is_not_sent(db, smtp):
    uid, [job] = await setup(db)
    s = await outbox.approve(db, uid, job, NOW + timedelta(hours=5), now=NOW)
    assert s.id not in [x.id for x in await outbox.due_sends(db, NOW)]
    assert s.id in [x.id for x in await outbox.due_sends(db, NOW + timedelta(hours=6))]


async def test_crash_mid_send_is_never_retried(db, smtp):
    uid, [job] = await setup(db)
    s = await outbox.approve(db, uid, job, NOW, now=NOW)
    s.status = "sending"  # worker died after marking, before SMTP finished
    await db.commit()
    assert await outbox.recover_stuck(db) == 1
    await db.refresh(s)
    assert s.status == "unknown" and await outbox.due_sends(db, NOW + timedelta(days=1)) == []


async def test_cancelled_mail_is_not_sent(db, smtp):
    uid, [job] = await setup(db)
    smtp["sent"].clear()
    s = await outbox.approve(db, uid, job, NOW, now=NOW)
    await outbox.cancel(db, uid, s.id)
    assert await outbox.deliver(db, s.id, now=NOW) == "skipped" and smtp["sent"] == []


async def test_wrong_password_at_send_time_fails_clearly(db, smtp):
    uid, [job] = await setup(db)
    s = await outbox.approve(db, uid, job, NOW, now=NOW)
    smtp["fail"] = aiosmtplib.SMTPAuthenticationError(535, "bad credentials")
    assert await outbox.deliver(db, s.id, now=NOW) == "failed"
    await db.refresh(s)
    assert s.status == "failed" and "App Password" in s.error


async def test_reschedule_moves_the_time(db, smtp):
    uid, [job] = await setup(db)
    s = await outbox.approve(db, uid, job, NOW, now=NOW)
    later = NOW + timedelta(days=1)
    await outbox.reschedule(db, uid, s.id, later, now=NOW)
    await db.refresh(s)
    assert s.send_at >= later
    assert (await db.execute(select(Send))).scalars().all() == [s]


# --- posts with several HR addresses -------------------------------------------------

TWO = ["hr@acme.com", "talent@acme.com"]


async def two_hr_job(db, uid, job):
    """Give the job (and its draft) two HR addresses, like a post that lists two."""
    j = await db.get(Job, job)
    j.hr_emails = TWO
    d = (await db.execute(select(Draft).where(Draft.job_id == job))).scalar_one()
    d.to_emails = TWO
    await db.commit()


async def test_one_email_goes_to_every_hr_address_together(db, smtp):
    uid, [job] = await setup(db)
    await two_hr_job(db, uid, job)
    await go_live(db, uid)
    smtp["sent"].clear()
    s = await outbox.approve(db, uid, job, NOW, now=NOW)
    assert s.to_emails == TWO and s.to_email == TWO[0]
    await outbox.deliver(db, s.id, now=NOW)
    [msg] = smtp["sent"]  # one mail, not two
    assert msg["To"] == "hr@acme.com, talent@acme.com"


async def test_you_can_leave_one_address_out(db, smtp):
    uid, [job] = await setup(db)
    await two_hr_job(db, uid, job)
    s = await outbox.approve(db, uid, job, NOW, to=["TALENT@acme.com"], now=NOW)
    assert s.to_emails == ["talent@acme.com"]
    with pytest.raises(outbox.NotAllowed, match="not an HR address"):
        await outbox.approve(db, uid, job, NOW, to=["someone@else.com"], now=NOW)


async def test_safety_rules_check_every_address(db, smtp):
    uid, [job] = await setup(db, hr="talent@acme.com", company="Acme")
    await go_live(db, uid)
    first = await outbox.approve(db, uid, job, NOW, now=NOW)  # talent@acme.com contacted for another Acme job
    await outbox.deliver(db, first.id, now=NOW)
    j2 = Job(user_id=uid, post_id=(await db.get(Job, job)).post_id, idx=9, company="Acme", role="ML Engineer",
             hr_emails=TWO, fit_score=80, verdict="STRONG MATCH")
    db.add(j2)
    await db.flush()
    resume = (await db.execute(select(Resume))).scalar_one()
    db.add(Draft(user_id=uid, job_id=j2.id, resume_id=resume.id, template_name="default-v1", to_emails=TWO,
                 subject="Application", body="Hello.", status="draft"))
    await db.commit()
    with pytest.raises(outbox.NotAllowed, match="talent@acme.com"):
        await outbox.approve(db, uid, j2.id, NOW + timedelta(days=1), now=NOW + timedelta(days=1))
    s = await outbox.approve(db, uid, j2.id, NOW + timedelta(days=1), to=["hr@acme.com"], now=NOW + timedelta(days=1))
    assert s.to_emails == ["hr@acme.com"]  # untick the one already emailed → allowed


async def test_test_mode_lists_every_address_it_would_have_used(db, smtp):
    uid, [job] = await setup(db)
    await two_hr_job(db, uid, job)
    smtp["sent"].clear()
    s = await outbox.approve(db, uid, job, NOW, now=NOW)
    await outbox.deliver(db, s.id, now=NOW)
    [msg] = smtp["sent"]
    assert msg["To"] == "me@gmail.com" and "hr@acme.com, talent@acme.com" in msg.get_body().get_content()


async def test_a_job_is_applied_to_once_whatever_addresses_are_picked(db, smtp):
    uid, [job] = await setup(db)
    await two_hr_job(db, uid, job)
    await outbox.approve(db, uid, job, NOW, to=["hr@acme.com"], now=NOW)
    with pytest.raises(outbox.NotAllowed, match="already scheduled"):
        await outbox.approve(db, uid, job, NOW, to=["talent@acme.com"], now=NOW)


async def test_emails_that_became_due_while_offline_are_spaced_out_again(db, smtp):
    """Laptop/server off at the planned times: when the sender comes back, they still go 3-8 min apart (no burst)."""
    uid, jobs = await setup(db, n_jobs=4)
    sends = [await outbox.approve(db, uid, j, NOW, now=NOW) for j in jobs]  # planned 3-8 min apart from 9:30
    back = NOW + timedelta(hours=2)  # the sender was off until 11:30
    sent_at = []
    t = back
    for _ in range(200):  # the worker: every 30 s, deliver whatever is due
        for snd in await outbox.due_sends(db, t, limit=20):
            if await outbox.deliver(db, snd.id, now=t) == "sent":
                sent_at.append(t)
        if len(sent_at) == len(sends):
            break
        t += timedelta(seconds=30)
    assert len(sent_at) == 4 and sent_at[0] == back
    gaps = [(b - a).total_seconds() for a, b in zip(sent_at, sent_at[1:], strict=False)]
    assert all(g >= outbox.GAP_MIN for g in gaps), gaps
