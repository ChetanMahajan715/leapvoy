"""Send queue: approve a draft → a scheduled Send → the sender worker delivers it when due.

Safety (checked at approval AND right before sending):
- test mode (default ON): every mail goes to the user's own sender inbox, "[TEST]" subject
- one email per job, to every HR address of the post at once (all in "To"; the user can leave some out)
- live mode: one mail per HR address per 30 days (whatever sender ID), one per company+role, do-not-contact,
  checked for EVERY address
- max `daily_limit` mails per sender per India day, 3–8 min random gaps
- never twice: unique send_key; a crash mid-send leaves status "unknown", which is never retried automatically
"""

import random
import uuid
from datetime import UTC, datetime, time, timedelta

import aiosmtplib
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import notify
from app.accounts.profile import get_profile
from app.db.models import DoNotContact, Draft, Job, Resume, SenderAccount, Send, UserSettings
from app.mailer import senders
from app.mailer.drafts import JobNotFound, is_outdated
from app.pipeline.report import IST

GAP_MIN, GAP_MAX = 180, 480  # seconds between two mails from the same sender
COOLDOWN = timedelta(days=30)
ACTIVE = ("scheduled", "sending", "sent", "unknown")  # counts for limits / "already contacted"
MORNING = time(10, 0)  # when mails pushed to the next day go out (IST)
RETRY_AFTER = timedelta(minutes=10)
MAX_ATTEMPTS = 3
_rng = random.Random()

__all__ = ["JobNotFound", "NotAllowed", "approve", "cancel", "deliver", "due_sends", "recover_stuck", "reschedule"]


class NotAllowed(ValueError):
    """The safety rules block this mail; the message says why."""


# --- settings -------------------------------------------------------------------------

async def is_test_mode(s: AsyncSession, user_id: uuid.UUID) -> bool:
    row = await s.get(UserSettings, user_id)
    return True if row is None else row.test_mode


async def set_test_mode(s: AsyncSession, user_id: uuid.UUID, on: bool) -> None:
    row = await s.get(UserSettings, user_id) or UserSettings(user_id=user_id)
    row.test_mode = on
    s.add(row)
    await s.commit()


# --- scheduling -------------------------------------------------------------------------

def _ist_day(t: datetime) -> datetime:
    return datetime.combine(t.astimezone(IST).date(), time(0), IST)


async def _slot(s: AsyncSession, sender: SenderAccount, wanted: datetime, exclude: int | None = None) -> datetime:
    """Earliest time ≥ wanted that keeps 3–8 min gaps and the daily limit for this sender.
    Sent mails count at the time they really went out (not their planned time): after the sender was off, overdue
    mails are spaced out again instead of going in one burst."""
    q = select(func.coalesce(Send.sent_at, Send.send_at)).where(Send.sender_id == sender.id, Send.status.in_(ACTIVE))
    if exclude:
        q = q.where(Send.id != exclude)
    taken = sorted((await s.execute(q)).scalars())
    t = wanted
    for _ in range(1000):
        day = _ist_day(t)
        on_day = [x for x in taken if day <= x < day + timedelta(days=1)]
        if len(on_day) >= sender.daily_limit:
            t = datetime.combine((day + timedelta(days=1)).date(), MORNING, IST).astimezone(UTC)
            continue
        clash = next((x for x in taken if abs((t - x).total_seconds()) < GAP_MIN), None)
        if clash is None:
            return t
        t = clash + timedelta(seconds=_rng.randint(GAP_MIN, GAP_MAX))
    raise NotAllowed("No free sending slot found")  # pragma: no cover


async def _check_live_rules(s: AsyncSession, user_id: uuid.UUID, job: Job, to: list[str], now: datetime,
                            exclude: int | None = None) -> None:
    blocked = (await s.execute(select(DoNotContact.email).where(DoNotContact.user_id == user_id,
                                                                DoNotContact.email.in_(to)))).scalars().first()
    if blocked:
        raise NotAllowed(f"{blocked} is on your do-not-contact list. Leave it out.")
    base = select(Send).where(Send.user_id == user_id, Send.status.in_(ACTIVE), Send.test_mode.is_(False))
    if exclude:
        base = base.where(Send.id != exclude)
    recent = (await s.execute(base.where(Send.to_emails.overlap(to), Send.created_at >= now - COOLDOWN))).scalars().first()
    if recent:
        hr = next(e for e in to if e in recent.to_emails)
        raise NotAllowed(f"Already emailed {hr} on {recent.send_at.astimezone(IST):%d %b}: one mail per HR per 30 days. "
                         f"Leave it out to send to the others.")
    same_role = (await s.execute(
        base.join(Job, Send.job_id == Job.id).where(
            func.lower(Job.company) == job.company.lower(), func.lower(Job.role) == job.role.lower(), Job.id != job.id
        )
    )).scalars().first()
    if same_role:
        raise NotAllowed(f"Already applied to {job.company} for {job.role}.")


async def approve(s: AsyncSession, user_id: uuid.UUID, job_id: int, when: datetime,
                  to: list[str] | str | None = None, now: datetime | None = None) -> Send:
    """Approve the job's draft and schedule it (when=now → as soon as pacing allows).
    to: which of the post's HR addresses get it (default: all of them, together in one email)."""
    now = now or datetime.now(UTC)
    job = (await s.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))).scalar_one_or_none()
    if job is None:
        raise JobNotFound(job_id)
    draft = (await s.execute(select(Draft).where(Draft.job_id == job.id))).scalar_one_or_none()
    if draft is None:
        raise NotAllowed("No email draft for this job yet. Write one first.")
    if draft.status == "needs_review":
        raise NotAllowed("This draft needs review: " + "; ".join(draft.issues))
    if await is_outdated(s, draft):
        raise NotAllowed("This email was written with an older resume or template. Rewrite it first.")
    sender = await senders.default_sender(s, user_id)
    if sender is None:
        raise NotAllowed("Connect a sender email first.")
    allowed = {e.lower() for e in draft.to_emails}
    picked = list(dict.fromkeys(e.strip().lower() for e in ([to] if isinstance(to, str) else to or draft.to_emails)))
    if not picked:
        raise NotAllowed("Pick at least one HR address.")
    if bad := [e for e in picked if e not in allowed]:
        raise NotAllowed(f"{bad[0]} is not an HR address from this job.")
    test = await is_test_mode(s, user_id)
    if not test:
        await _check_live_rules(s, user_id, job, picked, now)

    # one application per job (and mode), whichever addresses were picked
    earlier = (await s.execute(select(Send).where(Send.job_id == job.id, Send.test_mode.is_(test),
                                                  Send.status != "cancelled"))).scalars().first()
    if earlier:
        raise NotAllowed(f"This email is already {earlier.status} ({earlier.send_at.astimezone(IST):%d %b %I:%M %p} IST).")
    key = f"{job.id}:{'test' if test else 'live'}"
    send = (await s.execute(select(Send).where(Send.send_key == key))).scalar_one_or_none()  # a cancelled one: reuse
    send = send or Send(user_id=user_id, job_id=job.id, send_key=key)
    note = f"TEST MODE: this would have gone to: {', '.join(picked)}\n(Leapvoy only mails you while test mode is on.)\n\n"
    send.draft_id, send.sender_id, send.test_mode = draft.id, sender.id, test
    send.to_email, send.to_emails = picked[0], picked
    send.subject = ("[TEST] " if test else "") + draft.subject
    send.body = (note if test else "") + draft.body
    send.status, send.error, send.attempts = "scheduled", None, 0
    send.send_at = await _slot(s, sender, max(when, now), exclude=send.id)
    draft.status = "approved"
    s.add(send)
    await s.commit()
    return send


async def _own(s: AsyncSession, user_id: uuid.UUID, send_id: int) -> Send:
    send = (await s.execute(select(Send).where(Send.id == send_id, Send.user_id == user_id))).scalar_one_or_none()
    if send is None:
        raise NotAllowed(f"No email #{send_id}.")
    if send.status != "scheduled":
        raise NotAllowed(f"Email #{send_id} is {send.status}, not scheduled.")
    return send


async def cancel(s: AsyncSession, user_id: uuid.UUID, send_id: int) -> None:
    send = await _own(s, user_id, send_id)
    send.status = "cancelled"
    await s.commit()


async def reschedule(s: AsyncSession, user_id: uuid.UUID, send_id: int, when: datetime,
                     now: datetime | None = None) -> Send:
    send = await _own(s, user_id, send_id)
    send.send_at = await _slot(s, await s.get(SenderAccount, send.sender_id), max(when, now or datetime.now(UTC)),
                               exclude=send.id)
    await s.commit()
    return send


# --- delivery (sender worker) ------------------------------------------------------------

async def due_sends(s: AsyncSession, now: datetime, limit: int = 10) -> list[Send]:
    q = select(Send).where(Send.status == "scheduled", Send.send_at <= now).order_by(Send.send_at).limit(limit)
    return list((await s.execute(q)).scalars())


async def recover_stuck(s: AsyncSession) -> int:
    """On worker start: mails left 'sending' by a crash may or may not have gone out → 'unknown', never re-sent."""
    stuck = (await s.execute(select(Send).where(Send.status == "sending"))).scalars().all()
    for send in stuck:
        send.status, send.error = "unknown", "Worker stopped mid-send. Check your Sent folder; not retried."
    await s.commit()
    return len(stuck)


async def deliver(s: AsyncSession, send_id: int, now: datetime | None = None) -> str:
    """Send one due mail. Returns sent | postponed | cancelled | failed | retry | skipped."""
    now = now or datetime.now(UTC)
    send = (await s.execute(
        select(Send).where(Send.id == send_id, Send.status == "scheduled").with_for_update(skip_locked=True)
    )).scalar_one_or_none()
    if send is None:
        return "skipped"
    sender = await s.get(SenderAccount, send.sender_id)
    job = await s.get(Job, send.job_id)
    if not send.test_mode:
        try:
            await _check_live_rules(s, send.user_id, job, send.to_emails or [send.to_email], now, exclude=send.id)
        except NotAllowed as e:
            send.status, send.error = "cancelled", str(e)
            await s.commit()
            return "cancelled"
    slot = await _slot(s, sender, now, exclude=send.id)
    if slot > now:  # daily limit or gap since the last mail → wait
        send.send_at = slot
        today, then = (x.astimezone(IST) for x in (now, slot))
        if then.date() > today.date():  # the day's limit is used up: tell the user once per account per day
            await notify.once(s, send.user_id, "limit", f"{sender.id}:{today.date()}",
                              f"Daily limit reached for {sender.email}",
                              f"{sender.daily_limit} emails sent today. The rest go out tomorrow from "
                              f"{then.strftime('%I:%M %p').lstrip('0').lower()}.", {"screen": "scheduled"})
        await s.commit()
        return "postponed"

    send.status, send.attempts = "sending", send.attempts + 1
    await s.commit()  # from here a crash = "unknown", never a second send

    draft = await s.get(Draft, send.draft_id) if send.draft_id else None
    resume = await s.get(Resume, draft.resume_id) if draft else None
    name = (await get_profile(s, send.user_id)).get("full_name") or sender.email
    message = senders.build_message(
        name, sender.email, sender.email if send.test_mode else ", ".join(send.to_emails or [send.to_email]),
        send.subject, send.body,
        attachment=resume.pdf if resume else None, filename=resume.filename if resume else None,
    )
    login_failed = False
    try:
        await senders.smtp_send(message, sender.email, senders.password_of(sender))
    except senders.SenderLoginFailed as e:
        send.status, send.error, login_failed = "failed", str(e), True
    except (aiosmtplib.SMTPException, OSError) as e:  # network / server hiccup → try again later
        retry = send.attempts < MAX_ATTEMPTS
        send.status = "scheduled" if retry else "failed"
        send.error, send.send_at = f"{type(e).__name__}: {e}"[:500], now + RETRY_AFTER
    else:
        send.status, send.sent_at, send.message_id, send.error = "sent", now, message["Message-ID"], None
    if send.status == "failed":
        await notify.add(s, send.user_id, "send_failed", f"Couldn't send to {send.to_email}",
                         f"{job.company if job else 'Email'}: {send.error or 'unknown error'}"[:300],
                         {"send_id": send.id, "screen": "senders" if login_failed else "sent"})
    await s.commit()
    return {"scheduled": "retry"}.get(send.status, send.status)
