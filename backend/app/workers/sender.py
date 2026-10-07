"""Process entrypoint: sends due emails and checks for HR replies, 24/7. Run: python -m app.workers.sender"""

import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from app.core import heartbeat
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.models import SenderAccount, User
from app.db.session import get_sessionmaker
from app import notify
from app.accounts import deletion
from app.mailer import outbox, replies
from app.pipeline import retention

log = structlog.get_logger()
EVERY = 30  # seconds between send rounds
REPLIES_EVERY = 20  # rounds (~10 min) between inbox checks
MAINTENANCE_EVERY = 120  # rounds (~1 hour): delete accounts whose 7 days are over, clean posts older than 90 days


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    sm = get_sessionmaker()
    async with sm() as s:
        if stuck := await outbox.recover_stuck(s):
            log.warning("sender.unknown_after_crash", count=stuck)  # user checks Sent folder; never re-sent
    log.info("sender.worker_started", every=EVERY)
    rounds = 0
    while True:
        try:
            async with sm() as s:
                now = datetime.now(UTC)
                for send in await outbox.due_sends(s, now, limit=20):
                    result = await outbox.deliver(s, send.id, now=now)
                    log.info("sender.deliver", send_id=send.id, result=result)
                if rounds % REPLIES_EVERY == 0:
                    users = set((await s.execute(select(SenderAccount.user_id).join(User, User.id == SenderAccount.user_id)
                                                 .where(User.delete_after.is_(None)))).scalars())
                    for user_id in users:
                        if found := await replies.check_replies(s, user_id):
                            log.info("sender.replies", user_id=str(user_id), new=found)
                    await notify.morning_summary(s, now)
                await notify.push_pending(s, now)  # inbox rows made by any worker or the API → phones
            if rounds % MAINTENANCE_EVERY == 0:
                async with sm() as s:
                    if gone := await deletion.purge_due(s, datetime.now(UTC)):
                        log.info("maintenance.accounts_deleted", count=gone)
                    await retention.purge_old(s, datetime.now(UTC))
        except Exception:
            log.exception("sender.round_failed")
        rounds += 1
        heartbeat.beat()  # the server's health check: this loop is alive
        await asyncio.sleep(EVERY)


if __name__ == "__main__":
    asyncio.run(main())
