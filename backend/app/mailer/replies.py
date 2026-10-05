"""Reply tracker: read each sender's inbox (IMAP, read-only, mails are NOT marked as read), match replies from
HR addresses we emailed, mark the Send replied and stop further mails to that HR (do-not-contact)."""

import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import notify
from app.db.models import DoNotContact, Job, SenderAccount, Send
from app.mailer import senders

NOT_INTERESTED = re.compile(
    r"not (be )?(interested|moving forward|proceeding|shortlisted|a (good )?fit)|unfortunately|regret to inform|"
    r"position (has been|is) (filled|closed)|no longer (open|available|hiring)",
    re.I,
)


@dataclass(frozen=True)
class InboxMail:
    from_email: str
    date: datetime
    subject: str
    text: str


def aware(d: datetime) -> datetime:
    """Some mail servers send dates without a time zone; treat those as UTC."""
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _fetch(host: str, email: str, password: str, since: date) -> list[InboxMail]:
    from imap_tools import A, MailBox  # imported here: only the server worker needs it

    with MailBox(host).login(email, password, "INBOX") as box:
        return [
            InboxMail(m.from_.lower(), aware(m.date), m.subject, (m.text or m.html or "")[:2000])
            for m in box.fetch(A(date_gte=since), mark_seen=False, bulk=True)
        ]


async def check_replies(s: AsyncSession, user_id: uuid.UUID) -> int:
    """Returns how many new replies were found."""
    found = 0
    accounts = (await s.execute(select(SenderAccount).where(SenderAccount.user_id == user_id))).scalars().all()
    for acc in accounts:
        waiting = (await s.execute(select(Send).where(
            Send.sender_id == acc.id, Send.status == "sent", Send.test_mode.is_(False), Send.replied_at.is_(None)
        ))).scalars().all()
        if not waiting:
            continue
        by_hr = {hr: send for send in waiting for hr in (send.to_emails or [send.to_email])}  # any address counts
        since = min(send.sent_at for send in waiting).date()
        host = senders.PROVIDERS[acc.provider].imap_host
        inbox = await asyncio.to_thread(_fetch, host, acc.email, senders.password_of(acc), since)
        for mail in sorted(inbox, key=lambda m: m.date):
            send = by_hr.get(mail.from_email.lower())
            if send is None or send.replied_at is not None or mail.date < send.sent_at:
                continue
            send.replied_at, send.reply_snippet = mail.date, " ".join(mail.text.split())[:300]
            reason = "not interested" if NOT_INTERESTED.search(f"{mail.subject} {mail.text}") else "replied"
            await s.execute(insert(DoNotContact).values(user_id=user_id, email=mail.from_email.lower(), reason=reason)
                            .on_conflict_do_nothing(index_elements=["user_id", "email"]))
            job = await s.get(Job, send.job_id)
            await notify.add(s, user_id, "reply", f"{job.company if job else mail.from_email} replied",
                             send.reply_snippet[:200], {"send_id": send.id, "screen": "sent"})
            found += 1
    await s.commit()
    return found
