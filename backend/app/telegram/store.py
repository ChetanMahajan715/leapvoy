"""Per-user DB access for Telegram accounts, channels and posts. Every query filters by user_id."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt, encrypt, master_key
from app.db.models import Channel, Post, TelegramAccount, User


@dataclass(frozen=True)
class IncomingPost:
    tg_message_id: int
    text: str
    posted_at: datetime


async def get_or_create_user(s: AsyncSession, email: str) -> uuid.UUID:
    email = email.strip().lower()
    # password_hash "!" = unusable until real sign-up (Step 6)
    await s.execute(
        insert(User).values(id=uuid.uuid4(), email=email, password_hash="!").on_conflict_do_nothing(
            index_elements=["email"]
        )
    )
    user_id = (await s.execute(select(User.id).where(User.email == email))).scalar_one()
    await s.commit()
    return user_id


async def save_session(s: AsyncSession, user_id: uuid.UUID, phone: str, session_str: str) -> None:
    blob = encrypt(session_str.encode(), master_key(), user_id.bytes)
    stmt = insert(TelegramAccount).values(user_id=user_id, phone=phone, session_enc=blob)
    await s.execute(
        stmt.on_conflict_do_update(index_elements=["user_id"], set_={"phone": phone, "session_enc": blob})
    )
    await s.commit()


async def load_session(s: AsyncSession, user_id: uuid.UUID) -> str | None:
    blob = (
        await s.execute(select(TelegramAccount.session_enc).where(TelegramAccount.user_id == user_id))
    ).scalar_one_or_none()
    return None if blob is None else decrypt(blob, master_key(), user_id.bytes).decode()


async def delete_session(s: AsyncSession, user_id: uuid.UUID) -> None:
    await s.execute(delete(TelegramAccount).where(TelegramAccount.user_id == user_id))
    await s.commit()


async def users_with_telegram(s: AsyncSession) -> list[uuid.UUID]:
    return list((await s.execute(select(TelegramAccount.user_id).join(User, User.id == TelegramAccount.user_id)
                                 .where(User.delete_after.is_(None)))).scalars())  # paused while deletion is pending


async def upsert_channels(s: AsyncSession, user_id: uuid.UUID, chats: list[tuple[int, str, str | None]]) -> None:
    """chats = [(tg_chat_id, title, username)]. Keeps enabled flag and cursor of known channels."""
    if not chats:
        return
    stmt = insert(Channel).values(
        [{"user_id": user_id, "tg_chat_id": cid, "title": title, "username": uname} for cid, title, uname in chats]
    )
    await s.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "tg_chat_id"],
            set_={"title": stmt.excluded.title, "username": stmt.excluded.username},
        )
    )
    await s.commit()


async def set_enabled(s: AsyncSession, user_id: uuid.UUID, tg_chat_ids: list[int], enabled: bool) -> int:
    result = await s.execute(
        update(Channel)
        .where(Channel.user_id == user_id, Channel.tg_chat_id.in_(tg_chat_ids))
        .values(enabled=enabled)
    )
    await s.commit()
    return result.rowcount


async def list_channels(s: AsyncSession, user_id: uuid.UUID, enabled_only: bool = False) -> list[Channel]:
    q = select(Channel).where(Channel.user_id == user_id)
    if enabled_only:
        q = q.where(Channel.enabled)
    return list((await s.execute(q.order_by(Channel.title).execution_options(populate_existing=True))).scalars())


async def get_enabled_channel(s: AsyncSession, user_id: uuid.UUID, tg_chat_id: int) -> Channel | None:
    return (
        await s.execute(
            select(Channel)
            .where(Channel.user_id == user_id, Channel.tg_chat_id == tg_chat_id, Channel.enabled)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def save_posts(s: AsyncSession, user_id: uuid.UUID, channel_id: int, posts: list[IncomingPost]) -> int:
    """Idempotent: already-saved messages are skipped; cursor only moves forward. Returns # inserted."""
    if not posts:
        return 0
    stmt = (
        insert(Post)
        .values(
            [
                {
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "tg_message_id": p.tg_message_id,
                    "text": p.text.replace("\x00", ""),  # Postgres text can't hold NUL
                    "posted_at": p.posted_at,
                }
                for p in posts
            ]
        )
        .on_conflict_do_nothing(index_elements=["channel_id", "tg_message_id"])
        .returning(Post.id)
    )
    inserted = len((await s.execute(stmt)).all())
    await s.execute(
        update(Channel)
        .where(Channel.id == channel_id, Channel.user_id == user_id)
        .values(last_message_id=func.greatest(Channel.last_message_id, max(p.tg_message_id for p in posts)))
    )
    await s.commit()
    return inserted
