"""Delete account with a 7-day grace period. Asking stops everything at once (devices signed out, scheduled emails
cancelled, Telegram reading and AI work paused). Signing in during the 7 days shows "Keep my account"; nothing is
restored silently. After 7 days the account and every row of its data are deleted (and Telegram is logged out)."""

import uuid
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Device, Send, User
from app.telegram import store as tg_store

log = structlog.get_logger()
GRACE = timedelta(days=7)


async def request_deletion(s: AsyncSession, user: User, now: datetime) -> datetime:
    user.delete_after = now + GRACE
    await s.execute(update(Device).where(Device.user_id == user.id, Device.revoked_at.is_(None)).values(revoked_at=now))
    await s.execute(update(Send).where(Send.user_id == user.id, Send.status == "scheduled")
                    .values(status="cancelled", error="Cancelled: account deletion was requested."))
    await s.commit()
    return user.delete_after


async def restore(s: AsyncSession, user: User) -> None:
    user.delete_after = None
    await s.commit()


async def telegram_log_out(session_str: str) -> None:
    """End the Telegram session on Telegram's side too (best effort)."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    st = get_settings()
    if not (st.telegram_api_id and st.telegram_api_hash):
        return
    client = TelegramClient(StringSession(session_str), st.telegram_api_id, st.telegram_api_hash)
    try:
        await client.connect()
        if await client.is_user_authorized():
            await client.log_out()
    finally:
        await client.disconnect()


async def purge_due(s: AsyncSession, now: datetime) -> int:
    """Delete accounts whose 7 days are over. Every table cascades from users. Returns how many were deleted."""
    due = (await s.execute(select(User).where(User.delete_after.is_not(None), User.delete_after <= now))).scalars().all()
    for user in due:
        user_id: uuid.UUID = user.id
        session_str = await tg_store.load_session(s, user_id)
        if session_str:
            try:
                await telegram_log_out(session_str)
            except Exception:  # noqa: BLE001 - offline: the account is still deleted here
                log.warning("deletion.telegram_logout_failed", user_id=str(user_id))
        await s.delete(user)
        await s.commit()
        log.info("deletion.account_deleted", user_id=str(user_id))
    return len(due)
