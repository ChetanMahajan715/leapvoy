"""Sender email IDs: App Password over SMTP (Gmail/Outlook/Zoho/Yahoo), stored AES-GCM encrypted."""

import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import aiosmtplib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt, encrypt, master_key
from app.db.models import SenderAccount


@dataclass(frozen=True)
class Provider:
    smtp_host: str
    imap_host: str
    app_password_help: str
    smtp_port: int = 587  # STARTTLS


PROVIDERS = {
    "gmail": Provider("smtp.gmail.com", "imap.gmail.com", "https://myaccount.google.com/apppasswords"),
    "outlook": Provider("smtp-mail.outlook.com", "outlook.office365.com", "https://account.live.com/proofs/AppPassword"),
    "zoho": Provider("smtp.zoho.in", "imap.zoho.in", "https://accounts.zoho.in/home#security/app_password"),
    "yahoo": Provider("smtp.mail.yahoo.com", "imap.mail.yahoo.com", "https://login.yahoo.com/myaccount/security/"),
}
DOMAINS = {
    "gmail.com": "gmail", "googlemail.com": "gmail", "outlook.com": "outlook", "hotmail.com": "outlook",
    "live.com": "outlook", "zoho.com": "zoho", "zoho.in": "zoho", "zohomail.in": "zoho", "yahoo.com": "yahoo",
    "yahoo.in": "yahoo",
}
_smtp_send = aiosmtplib.send  # swapped in tests


class SenderLoginFailed(RuntimeError):
    pass


def provider_for(email: str) -> str:
    domain = email.rsplit("@", 1)[-1].lower()
    if domain not in DOMAINS:
        raise ValueError(f"{domain} isn't supported yet. Use a Gmail, Outlook, Zoho or Yahoo address.")
    return DOMAINS[domain]


def build_message(
    from_name: str, from_email: str, to: str, subject: str, body: str,
    attachment: bytes | None = None, filename: str | None = None,
) -> EmailMessage:
    """Plain-text personal email to one or more addresses ("a@x.com, b@y.com"), optional PDF, no HTML, no tracking."""
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=from_email.rsplit("@", 1)[-1])
    msg.set_content(body)
    if attachment:
        msg.add_attachment(attachment, maintype="application", subtype="pdf", filename=filename or "resume.pdf")
    return msg


async def smtp_send(message: EmailMessage, email: str, password: str) -> None:
    p = PROVIDERS[provider_for(email)]
    try:
        await _smtp_send(message, hostname=p.smtp_host, port=p.smtp_port, username=email, password=password,
                         timeout=60)
    except aiosmtplib.SMTPAuthenticationError as e:
        raise SenderLoginFailed(
            f"{email}: login refused. Use an App Password (not your normal password): {p.app_password_help}"
        ) from e


def password_of(acc: SenderAccount) -> str:
    return decrypt(acc.password_enc, master_key(), acc.user_id.bytes).decode()


async def add_sender(s: AsyncSession, user_id: uuid.UUID, email: str, password: str, name: str = "Leapvoy") -> SenderAccount:
    """Test the login by mailing the address itself; only then save (encrypted). First sender = default."""
    email, password = email.strip().lower(), password.replace(" ", "")
    provider = provider_for(email)
    await smtp_send(
        build_message(name, email, email, "Leapvoy is connected",
                      "Leapvoy can now send emails from this address.\n\nNothing is sent to anyone else "
                      "until you approve it (and turn test mode off)."),
        email, password,
    )
    acc = (await s.execute(
        select(SenderAccount).where(SenderAccount.user_id == user_id, SenderAccount.email == email)
    )).scalar_one_or_none()
    has_default = (await default_sender(s, user_id)) is not None
    acc = acc or SenderAccount(user_id=user_id, email=email, is_default=not has_default)
    acc.provider, acc.password_enc = provider, encrypt(password.encode(), master_key(), user_id.bytes)
    s.add(acc)
    await s.commit()
    return acc


async def default_sender(s: AsyncSession, user_id: uuid.UUID) -> SenderAccount | None:
    return (await s.execute(
        select(SenderAccount).where(SenderAccount.user_id == user_id, SenderAccount.is_default)
    )).scalar_one_or_none()
