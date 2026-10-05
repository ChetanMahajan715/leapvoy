"""Chats and messages, always scoped by user_id."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chat, Message


async def create_chat(s: AsyncSession, user_id: uuid.UUID, title: str = "New chat") -> Chat:
    chat = Chat(user_id=user_id, title=title)
    s.add(chat)
    await s.commit()
    return chat


async def get_chat(s: AsyncSession, user_id: uuid.UUID, chat_id: int) -> Chat | None:
    return (await s.execute(select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id))).scalar_one_or_none()


async def list_chats(s: AsyncSession, user_id: uuid.UUID, q: str | None = None, limit: int = 200) -> list[Chat]:
    """Pinned first, then most recently active. q = words in the title or any message."""
    query = select(Chat).where(Chat.user_id == user_id)
    if q and q.strip():
        words = func.plainto_tsquery("simple", q)
        in_messages = select(Message.chat_id).where(Message.user_id == user_id, Message.search.op("@@")(words))
        query = query.where(or_(Chat.title.ilike(f"%{q.strip()}%"), Chat.id.in_(in_messages)))
    query = query.order_by(Chat.pinned.desc(), Chat.updated_at.desc(), Chat.id.desc()).limit(limit)
    return list((await s.execute(query)).scalars())


async def update_chat(s: AsyncSession, user_id: uuid.UUID, chat_id: int, **fields) -> Chat | None:
    chat = await get_chat(s, user_id, chat_id)
    if chat is None:
        return None
    for k, v in fields.items():
        setattr(chat, k, v)
    await s.commit()
    return chat


async def delete_chat(s: AsyncSession, user_id: uuid.UUID, chat_id: int) -> bool:
    result = await s.execute(delete(Chat).where(Chat.id == chat_id, Chat.user_id == user_id))
    await s.commit()
    return result.rowcount > 0


async def add_message(
    s: AsyncSession, user_id: uuid.UUID, chat_id: int, role: str, content: str, cards: list[dict[str, Any]] | None = None
) -> Message:
    msg = Message(chat_id=chat_id, user_id=user_id, role=role, content=content, cards=cards or [])
    s.add(msg)
    await s.execute(update(Chat).where(Chat.id == chat_id, Chat.user_id == user_id).values(updated_at=datetime.now(UTC)))
    await s.commit()
    return msg


async def messages(s: AsyncSession, user_id: uuid.UUID, chat_id: int, limit: int | None = None) -> list[Message]:
    """Oldest first. limit = only the last N (for the AI's context)."""
    q = select(Message).where(Message.chat_id == chat_id, Message.user_id == user_id).order_by(Message.id.desc())
    if limit:
        q = q.limit(limit)
    return list(reversed((await s.execute(q)).scalars().all()))
