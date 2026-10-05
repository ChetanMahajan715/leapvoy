"""Process entrypoint: one live Telegram reader per connected user. Run: python -m app.workers.telegram_reader"""

import asyncio
import uuid
from datetime import UTC, datetime

import structlog

from app import notify
from app.core import heartbeat
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import get_sessionmaker
from app.telegram import reader, store

log = structlog.get_logger()
RESCAN_EVERY = 60  # seconds; picks up users who connect Telegram later


async def keep_running(user_id: uuid.UUID, sm) -> None:
    """Restart the reader on errors with backoff (5 s → 5 min); stop if the session is revoked."""
    delay = 5
    while True:
        try:
            await reader.run_account(user_id, sm)
            delay = 5  # clean disconnect → reconnect quickly
        except reader.SessionRevoked:
            log.error("telegram.session_revoked", user_id=str(user_id))
            async with sm() as s:
                await notify.once(s, user_id, "telegram_out", datetime.now(UTC).date().isoformat(),
                                  "Telegram signed Leapvoy out",
                                  "No new posts until you log in again: Setup → Channels.", {"screen": "channels"})
                await s.commit()
            return
        except Exception:
            log.exception("telegram.reader_crashed", user_id=str(user_id), retry_in=delay)
            delay = min(delay * 2, 300)
        await asyncio.sleep(delay)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    sm = get_sessionmaker()
    log.info("telegram.worker_started", rescan_every=RESCAN_EVERY)
    running: dict[uuid.UUID, asyncio.Task] = {}
    while True:
        async with sm() as s:
            users = await store.users_with_telegram(s)
        for user_id in users:
            if user_id not in running or running[user_id].done():
                log.info("telegram.reader_start", user_id=str(user_id))
                running[user_id] = asyncio.create_task(keep_running(user_id, sm))
        for user_id in set(running) - set(users):  # disconnected → stop reading
            running.pop(user_id).cancel()
        heartbeat.beat()  # the server's health check: this loop is alive
        await asyncio.sleep(RESCAN_EVERY)


if __name__ == "__main__":
    asyncio.run(main())
