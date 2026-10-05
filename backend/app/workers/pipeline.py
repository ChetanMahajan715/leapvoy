"""Process entrypoint: runs the AI pipeline on new posts for every user, in real time. Run: python -m app.workers.pipeline

Smart: only posts from the last RECENT_DAYS (never an old backlog), and it pauses when the free daily AI allowance
is nearly used up so the user's chat keeps working (app.llm.usage).
"""

import asyncio
from datetime import UTC, datetime, timedelta

import structlog

from app import notify
from app.core import heartbeat
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import get_sessionmaker
from app.llm import usage
from app.pipeline import graph, report, store

log = structlog.get_logger()
EVERY = 30  # seconds between rounds
PER_ROUND = 10  # posts per user per round; keeps under Groq's 8K tokens/minute free limit
RECENT_DAYS = 3  # older posts are left for "check Telegram" on that day; jobs go stale fast


async def run_round(sm, now: datetime) -> dict[str, int]:
    """Up to PER_ROUND recent posts per user. Checks the allowance before every post and stops at the first
    rate limit: the free limits refill over time; hammering them only delays the user's chat."""
    async with sm() as s:
        users = await store.users_with_pending(s)
    total: dict[str, int] = {}
    for user_id in users:
        async with sm() as s:
            post_ids = await store.next_posts(s, user_id, PER_ROUND, since=now - timedelta(days=RECENT_DAYS))
        for post_id in post_ids:
            async with sm() as s:
                if not await usage.background_allowed(s, now):
                    total["paused"] = 1
                    for waiting in users:  # everyone whose posts now wait, once a day
                        await notify.once(s, waiting, "ai_paused", now.astimezone(report.IST).date().isoformat(),
                                          "Free AI is nearly used up for today",
                                          "New posts wait and are checked automatically as it refills. Chat still works.",
                                          {"screen": "jobs"})
                    await s.commit()
                    return total
            stage = await graph.run_post(sm, post_id)
            total[stage] = total.get(stage, 0) + 1
            if stage in ("rate_limited", "unreachable"):  # retry next round; hammering won't help
                log.info("pipeline.round", user_id=str(user_id), **total)
                return total
        if total:
            log.info("pipeline.round", user_id=str(user_id), **total)
    return total


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    usage.install()
    sm = get_sessionmaker()
    log.info("pipeline.worker_started", every=EVERY, recent_days=RECENT_DAYS)
    while True:
        try:
            await run_round(sm, datetime.now(UTC))
        except Exception:
            log.exception("pipeline.round_failed")
        heartbeat.beat()  # the server's health check: this loop is alive
        await asyncio.sleep(EVERY)


if __name__ == "__main__":
    asyncio.run(main())
