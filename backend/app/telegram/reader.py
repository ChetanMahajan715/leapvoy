"""Read-only Telegram reader: catch-up, backfill and live posts for one user.

Never call send/join/forward/read-acknowledge APIs here, Leapvoy only reads.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from app.core.config import get_settings
from app.telegram import store
from app.telegram.store import IncomingPost

log = structlog.get_logger()
SessionMaker = async_sessionmaker[AsyncSession]
BATCH = 100
FIRST_LOOKBACK = timedelta(days=2)  # first read of a channel; older posts need `backfill`
RECHECK_EVERY = 600  # seconds; periodic catch-up covers missed live updates + newly enabled channels


class SessionRevoked(Exception):
    """User logged Leapvoy out from Telegram (or session expired) → needs a new login."""


def to_incoming(msg) -> IncomingPost | None:
    text = (msg.message or "").strip()  # text, or a photo/file caption
    return IncomingPost(msg.id, text, msg.date) if text else None


async def iter_posts(
    client,
    chat_id: int,
    min_id: int,
    since: datetime | None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[IncomingPost]:
    """Posts newer than min_id (and since), oldest first. FloodWait → wait, resume after last seen."""
    while True:
        try:
            async for msg in client.iter_messages(chat_id, min_id=min_id, reverse=True, offset_date=since):
                min_id = msg.id
                if post := to_incoming(msg):
                    yield post
            return
        except FloodWaitError as e:
            log.warning("telegram.flood_wait", chat_id=chat_id, seconds=e.seconds)
            await sleep(e.seconds)


async def _save(sm: SessionMaker, user_id: uuid.UUID, channel_id: int, batch: list[IncomingPost]) -> int:
    async with sm() as s:
        return await store.save_posts(s, user_id, channel_id, batch)


async def catch_up(
    client,
    sm: SessionMaker,
    user_id: uuid.UUID,
    since: datetime | None = None,
    from_start: bool = False,
    now: datetime | None = None,
) -> int:
    """Save missed posts for every enabled channel. from_start + since = backfill. Returns # new posts."""
    async with sm() as s:
        channels = await store.list_channels(s, user_id, enabled_only=True)
    total = 0
    for ch in channels:
        min_id = 0 if from_start else ch.last_message_id
        start = since or (None if min_id else (now or datetime.now(UTC)) - FIRST_LOOKBACK)
        batch: list[IncomingPost] = []
        try:
            async for post in iter_posts(client, ch.tg_chat_id, min_id, start):
                batch.append(post)
                if len(batch) == BATCH:  # save as we go → a crash loses at most one batch
                    total += await _save(sm, user_id, ch.id, batch)
                    batch = []
        except Exception:
            log.exception("telegram.catch_up_failed", user_id=str(user_id), chat_id=ch.tg_chat_id)
        total += await _save(sm, user_id, ch.id, batch)
    return total


async def handle_new_message(sm: SessionMaker, user_id: uuid.UUID, chat_id: int, msg) -> bool:
    post = to_incoming(msg)
    if post is None:
        return False
    async with sm() as s:
        channel = await store.get_enabled_channel(s, user_id, chat_id)
        if channel is None:
            return False
        await store.save_posts(s, user_id, channel.id, [post])
    return True


async def connect(session_str: str) -> TelegramClient:
    """Connected, authorized client with its entity cache filled (StringSession keeps no entities)."""
    settings = get_settings()
    if not (settings.telegram_api_id and settings.telegram_api_hash):
        raise RuntimeError("TELEGRAM_API_ID / TELEGRAM_API_HASH missing in .env")
    client = TelegramClient(
        StringSession(session_str),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        flood_sleep_threshold=120,  # Telethon auto-sleeps short flood waits
    )
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise SessionRevoked
    await client.get_dialogs()
    return client


async def run_account(user_id: uuid.UUID, sm: SessionMaker) -> None:
    """Live-read one user's channels until disconnected."""
    async with sm() as s:
        session_str = await store.load_session(s, user_id)
    if session_str is None:
        return
    client = await connect(session_str)
    try:

        async def on_new_message(event):
            if await handle_new_message(sm, user_id, event.chat_id, event.message):
                log.info("telegram.post_saved", user_id=str(user_id), chat_id=event.chat_id)

        client.add_event_handler(on_new_message, events.NewMessage())

        async def recheck():
            while True:
                await asyncio.sleep(RECHECK_EVERY)
                await client.get_dialogs()  # learn newly joined channels
                await catch_up(client, sm, user_id)

        saved = await catch_up(client, sm, user_id)
        log.info("telegram.caught_up", user_id=str(user_id), new_posts=saved)
        rechecker = asyncio.create_task(recheck())
        try:
            await client.run_until_disconnected()
        finally:
            rechecker.cancel()
    finally:
        await client.disconnect()
