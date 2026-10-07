"""Send queue: approve a draft → a scheduled Send → the sender worker delivers it when due.

Safety:
- test mode (default ON): every mail goes to the user's own sender inbox, "[TEST]" subject; tests can repeat
- one email to every address of the post at once (all in "To"; the user can leave some out)
- live mode, at approval: an address emailed in the last 30 days, a company+role already applied to, or this
  job's email already sent → NeedsConfirm with the reasons; the user may send anyway (their choice, 7 Oct)
- do-not-contact: always blocked, checked at approval AND right before sending
- max `daily_limit` mails per sender per India day, 3–8 min random gaps
- never twice by accident: unique send_key per email (a resend gets its own); a crash mid-send leaves status
  "unknown", which is never retried automatically
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

__all__ = ["JobNotFound", "NeedsConfirm", "NotAllowed", "approve", "cancel", "deliver", "due_sends", "recover_stuck", "reschedule"]


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


class NeedsConfirm(NotAllowed):
    """Not a block: the user is told why (e.g. that address was emailed 3 days ago) and may send anyway."""

    def __init__(self, warnings: list[str]):
        super().__init__(" ".join(warnings))
        self.warnings = warnings


def _ago(when: datetime, now: datetime) -> str:
    days = (now - when).days
    return "today" if days < 1 else "yesterday" if days == 1 else f"{days} days ago"


async def _do_not_contact(s: AsyncSession, user_id: uuid.UUID, to: list[str]) -> None:
    """The one hard rule left: the user's own do-not-contact list."""
    blocked = (await s.execute(select(DoNotContact.email).where(DoNotContact.user_id == user_id,
                                                                DoNotContact.email.in_(to)))).scalars().first()
    if blocked:
        raise NotAllowed(f"{blocked} is on your do-not-contact list. Leave it out.")


async def warnings_for(s: AsyncSession, user_id: uuid.UUID, job: Job, to: list[str], now: datetime) -> list[str]:
    """Live mode: what the user should know before sending (they may still send). Was: hard 30-day / one-per-role
    blocks; the user asked for a warning they can approve instead (7 Oct)."""
    base = select(Send).where(Send.user_id == user_id, Send.status.in_(ACTIVE), Send.test_mode.is_(False))
    out: list[str] = []
    for e in to:
        last = (await s.execute(base.where(Send.to_emails.any(e), Send.created_at >= now - COOLDOWN)
                                .order_by(Send.send_at.desc()).limit(1))).scalars().first()
        if last:
            when = last.sent_at or last.send_at
            verb = "already emailed" if last.status in ("sent", "unknown") else "already have an email scheduled to"
            out.append(f"You {verb} {e} {_ago(when, now)} ({when.astimezone(IST):%d %b, %I:%M %p} IST).")
    same_role = (await s.execute(base.join(Job, Send.job_id == Job.id).where(
        func.lower(Job.company) == job.company.lower(), func.lower(Job.role) == job.role.lower(), Job.id != job.id
    ))).scalars().first()
    if same_role:
        out.append(f"You already applied to {job.company} for {job.role} from another post.")
    return out


async def send_notes(s: AsyncSession, user_id: uuid.UUID, job: Job, picked: list[str], now: datetime,
                     test: bool) -> list[str]:
    """What to tell the user before this job's email goes to `picked` ([] = nothing to worry about). Raises
    NotAllowed only for real blocks: a copy already waiting in the queue, or a do-not-contact address."""
    mine = select(Send).where(Send.job_id == job.id, Send.test_mode.is_(test))
    waiting = (await s.execute(mine.where(Send.status.in_(("scheduled", "sending"))))).scalars().first()
    if waiting:  # two copies queued at once is never wanted: change the waiting one instead
        raise NotAllowed(f"This email is already scheduled ({waiting.send_at.astimezone(IST):%d %b %I:%M %p} IST). "
                         "Edit or move that one instead.")
    if test:
        return []
    await _do_not_contact(s, user_id, picked)
    notes = await warnings_for(s, user_id, job, picked, now)
    sent = (await s.execute(mine.where(Send.status.in_(("sent", "unknown"))).order_by(Send.send_at.desc()))).scalars().first()
    if sent:
        notes.insert(0, f"This job's email was already sent {_ago(sent.sent_at or sent.send_at, now)}. "
                        "This sends another one.")
    return list(dict.fromkeys(notes))


def _copy_text(send: Send, draft: Draft) -> None:
    """The email as it will go out: the draft, marked [TEST] (with who it was meant for) in test mode."""
    note = (f"TEST MODE: this would have gone to: {', '.join(send.to_emails or [send.to_email])}\n"
            "(Leapvoy only mails you while test mode is on.)\n\n")
    send.subject = ("[TEST] " if send.test_mode else "") + draft.subject
    send.body = (note if send.test_mode else "") + draft.body


async def refresh_waiting(s: AsyncSession, user_id: uuid.UUID, job_id: int) -> bool:
    """After the user edits or rewrites a job's email: a copy still waiting to go out takes the new text (same time)."""
    draft = (await s.execute(select(Draft).where(Draft.job_id == job_id, Draft.user_id == user_id))).scalar_one_or_none()
    send = (await s.execute(select(Send).where(Send.job_id == job_id, Send.user_id == user_id,
                                               Send.status == "scheduled"))).scalars().first()
    if draft is None or send is None:
        return False
    _copy_text(send, draft)
    send.draft_id = draft.id
    if draft.status != "needs_review":
        draft.status = "approved"
    await s.commit()
    return True


async def hide(s: AsyncSession, user_id: uuid.UUID, send_id: int) -> None:
    """Delete from the Scheduled / Sent list: a waiting email is cancelled first. The row stays (hidden), so a sent
    email still counts for "you emailed this address 3 days ago"."""
    send = (await s.execute(select(Send).where(Send.id == send_id, Send.user_id == user_id))).scalar_one_or_none()
    if send is None:
        raise NotAllowed(f"No email #{send_id}.")
    if send.status == "sending":
        raise NotAllowed("This email is going out right now. Try again in a minute.")
    if send.status == "scheduled":
        send.status = "cancelled"
    send.hidden = True
    await s.commit()


async def approve(s: AsyncSession, user_id: uuid.UUID, job_id: int, when: datetime,
                  to: list[str] | str | None = None, now: datetime | None = None, confirm: bool = False) -> Send:
    """Approve the job's draft and schedule it (when=now → as soon as pacing allows).
    to: which of the post's addresses get it (default: all of them, together in one email).
    Live mode: raises NeedsConfirm with the reasons (address emailed recently, role already applied, this email
    already sent) unless confirm=True: the user decides. A second email for a job (resend) gets its own row."""
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
        raise NotAllowed("Pick at least one address.")
    if bad := [e for e in picked if e not in allowed]:
        raise NotAllowed(f"{bad[0]} is not an address from this job.")
    test = await is_test_mode(s, user_id)
    mode = "test" if test else "live"
    mine = select(Send).where(Send.job_id == job.id, Send.test_mode.is_(test))
    notes = await send_notes(s, user_id, job, picked, now, test)
    if notes and not confirm:
        raise NeedsConfirm(notes)
    # a cancelled one is reused; otherwise each email of this job (and mode) gets its own never-twice key
    send = (await s.execute(mine.where(Send.status == "cancelled").order_by(Send.id.desc()))).scalars().first()
    if send is None:
        n = await s.scalar(select(func.count()).select_from(Send).where(Send.job_id == job.id, Send.test_mode.is_(test)))
        send = Send(user_id=user_id, job_id=job.id, send_key=f"{job.id}:{mode}" + (f":{n + 1}" if n else ""))
    send.draft_id, send.sender_id, send.test_mode = draft.id, sender.id, test
    send.to_email, send.to_emails = picked[0], picked
    _copy_text(send, draft)
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
    if not send.test_mode:  # the 30-day / same-role notes were answered when the user approved; only the
        try:                  # do-not-contact list is checked again (an address may have been added since)
            await _do_not_contact(s, send.user_id, send.to_emails or [send.to_email])
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
