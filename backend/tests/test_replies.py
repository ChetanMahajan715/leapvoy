from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models import DoNotContact, Draft, Job, Send
from app.mailer import outbox, replies
from tests.conftest import requires_db
from tests.test_outbox import NOW, go_live, master_key, setup, smtp  # noqa: F401 (fixtures)

pytestmark = requires_db


def mail(frm, text="Thanks, let's talk.", minutes_after=60, subject="Re: Application for AI Engineer"):
    return replies.InboxMail(from_email=frm, date=NOW + timedelta(minutes=minutes_after), subject=subject, text=text)


@pytest.fixture
def inbox(monkeypatch):
    box = {"mails": []}

    def fake_fetch(host, email, password, since):
        return list(box["mails"])

    monkeypatch.setattr(replies, "_fetch", fake_fetch)
    return box


async def sent_live(db, uid, job):
    await go_live(db, uid)
    s = await outbox.approve(db, uid, job, NOW, now=NOW)
    await outbox.deliver(db, s.id, now=NOW)
    return s


async def test_reply_marks_job_replied_and_stops_further_mails(db, smtp, inbox):
    uid, [job] = await setup(db)
    s = await sent_live(db, uid, job)
    inbox["mails"] = [mail("HR0@company0.com")]
    assert await replies.check_replies(db, uid) == 1
    await db.refresh(s)
    assert s.replied_at is not None and "let's talk" in s.reply_snippet
    dnc = (await db.execute(select(DoNotContact))).scalar_one()
    assert (dnc.email, dnc.reason) == ("hr0@company0.com", "replied")


async def test_not_interested_reply_is_recorded_as_such(db, smtp, inbox):
    uid, [job] = await setup(db)
    await sent_live(db, uid, job)
    inbox["mails"] = [mail("hr0@company0.com", "Unfortunately we are not moving forward with your application.")]
    await replies.check_replies(db, uid)
    assert (await db.execute(select(DoNotContact.reason))).scalar_one() == "not interested"


async def test_unrelated_and_earlier_mails_are_ignored(db, smtp, inbox):
    uid, [job] = await setup(db)
    s = await sent_live(db, uid, job)
    inbox["mails"] = [mail("someone@else.com"), mail("hr0@company0.com", minutes_after=-60)]
    assert await replies.check_replies(db, uid) == 0
    await db.refresh(s)
    assert s.replied_at is None


async def test_test_mode_mails_are_not_tracked(db, smtp, inbox):
    uid, [job] = await setup(db)
    s = await outbox.approve(db, uid, job, NOW, now=NOW)  # test mode
    await outbox.deliver(db, s.id, now=NOW)
    inbox["mails"] = [mail("hr0@company0.com")]
    assert await replies.check_replies(db, uid) == 0


async def test_each_reply_counted_once(db, smtp, inbox):
    uid, [job] = await setup(db)
    await sent_live(db, uid, job)
    inbox["mails"] = [mail("hr0@company0.com")]
    await replies.check_replies(db, uid)
    assert await replies.check_replies(db, uid) == 0
    assert len((await db.execute(select(Send).where(Send.replied_at.is_not(None)))).all()) == 1


def test_mail_dates_without_timezone_become_utc():
    naive = datetime(2026, 9, 30, 10, 0)
    assert replies.aware(naive) == datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
    assert replies.aware(NOW) == NOW


async def test_reply_from_any_of_the_addresses_counts(db, smtp, inbox):
    uid, [job] = await setup(db)
    j = await db.get(Job, job)
    j.hr_emails = ["hr@acme.com", "talent@acme.com"]
    d = (await db.execute(select(Draft).where(Draft.job_id == job))).scalar_one()
    d.to_emails = j.hr_emails
    await db.commit()
    s = await sent_live(db, uid, job)
    inbox["mails"] = [mail("talent@acme.com")]
    assert await replies.check_replies(db, uid) == 1
    await db.refresh(s)
    assert s.replied_at is not None
    assert (await db.execute(select(DoNotContact.email))).scalar_one() == "talent@acme.com"
