"""Account recovery, all ₹0: forgot-password code by email, 2FA backup codes, server-side reset (last resort).

Rule: an email code resets ONLY the password. With 2FA on you still need the authenticator or a backup code,
so someone who gets into your mailbox can't bypass 2FA. Lost everything → `python -m app.accounts.cli reset`.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts import auth
from app.core.config import get_settings
from app.db.models import Device, PasswordReset, User
from app.mailer import senders

CODE_TTL = timedelta(minutes=15)
MAX_TRIES = 5
BACKUP_COUNT = 10
_BACKUP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i look-alikes


class ResetNotConfigured(RuntimeError):
    """SYSTEM_EMAIL / SYSTEM_EMAIL_PASSWORD missing in .env."""


def _keyed_hash(value: str) -> str:
    """Short codes are hashed with a server secret, so a leaked database can't be brute-forced offline."""
    key = (get_settings().jwt_secret or "").encode()
    return hmac.new(key, value.strip().lower().encode(), hashlib.sha256).hexdigest()


# --- 2FA backup codes ---------------------------------------------------------------------

def new_backup_codes(user: User) -> list[str]:
    """10 one-time codes like 'k3m9-x7qa'. Only their hashes are stored; shown to the user once."""
    codes = [
        "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(4)) + "-" +
        "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(4))
        for _ in range(BACKUP_COUNT)
    ]
    user.backup_codes = [_keyed_hash(c) for c in codes]
    return codes


def second_factor_ok(user: User, code: str) -> bool:
    """Authenticator code, or an unused backup code (which is used up, caller commits)."""
    if auth.code_ok(user, code):
        return True
    h = _keyed_hash(code)
    if h in (user.backup_codes or []):
        user.backup_codes = [c for c in user.backup_codes if c != h]
        return True
    return False


# --- forgot password ------------------------------------------------------------------------

def _configured() -> bool:
    s = get_settings()
    return bool(s.system_email and s.system_email_password)


async def send_code_email(to: str, code: str) -> None:
    s = get_settings()
    message = senders.build_message(
        "Leapvoy", s.system_email, to, f"Your Leapvoy code: {code}",
        f"Your Leapvoy password reset code is:\n\n    {code}\n\n"
        "It works for 15 minutes. If you didn't ask for this, ignore this email. Your password stays the same.",
    )
    await senders.smtp_send(message, s.system_email, s.system_email_password.replace(" ", ""))  # Google shows it with spaces


async def start_reset(s: AsyncSession, email: str) -> None:
    """Emails a 6-digit code if the account exists. Same answer either way (no account probing)."""
    if not _configured():
        raise ResetNotConfigured
    user = (await s.execute(select(User).where(User.email == email.strip().lower()))).scalar_one_or_none()
    if user is None or user.password_hash == "!":
        return
    now = datetime.now(UTC)
    await s.execute(update(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
                    .values(used_at=now))  # a newer code replaces older ones
    code = f"{secrets.randbelow(1_000_000):06d}"
    s.add(PasswordReset(user_id=user.id, code_hash=_keyed_hash(code), expires_at=now + CODE_TTL))
    await s.commit()
    await send_code_email(user.email, code)


async def finish_reset(s: AsyncSession, email: str, code: str, new_password: str) -> bool:
    user = (await s.execute(select(User).where(User.email == email.strip().lower()))).scalar_one_or_none()
    if user is None:
        return False
    now = datetime.now(UTC)
    pending = (await s.execute(
        select(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
        .order_by(PasswordReset.id.desc()).limit(1)
    )).scalar_one_or_none()
    if pending is None or pending.expires_at < now or pending.attempts >= MAX_TRIES:
        return False
    if not hmac.compare_digest(pending.code_hash, _keyed_hash(code)):
        pending.attempts += 1
        await s.commit()
        return False
    pending.used_at = now
    user.password_hash = auth.hash_password(new_password)
    await _log_out_everywhere(s, user.id, now)
    await s.commit()
    return True


async def _log_out_everywhere(s: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    await s.execute(update(Device).where(Device.user_id == user_id, Device.revoked_at.is_(None)).values(revoked_at=now))


# --- server reset (last resort) --------------------------------------------------------------

async def admin_reset(s: AsyncSession, email: str, new_password: str) -> bool:
    """Run on the server by its owner: new password, 2FA off, every device logged out."""
    user = (await s.execute(select(User).where(User.email == email.strip().lower()))).scalar_one_or_none()
    if user is None:
        return False
    now = datetime.now(UTC)
    user.password_hash = auth.hash_password(new_password)
    user.totp_enabled, user.totp_secret_enc, user.backup_codes = False, None, []
    await _log_out_everywhere(s, user.id, now)
    await s.commit()
    return True
