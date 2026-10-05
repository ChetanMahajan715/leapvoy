"""30-day cleanup of old posts. Removed: posts older than 30 India days (and their jobs and drafts) that never led to an
email. Kept forever: everything you emailed (the job, the email, replies), because the "one email per HR every
30 days" and "never apply twice" rules and your history need it. Before a day is cleaned, its counts are saved in
day_stats so Stats stay right for long periods."""

import uuid
from datetime import date, datetime, timedelta

import structlog
from sqlalchemy import and_, delete, exists, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, DayStats, Job, Post, Send
from app.pipeline import report

log = structlog.get_logger()
KEEP_DAYS = 30
FITS = ("TOP PRIORITY", "STRONG MATCH", "APPLY", "MAYBE")


def ist_date(col):
    # fixed +05:30 (India has no daylight saving); written inline so GROUP BY matches the SELECT
    return func.date(func.timezone(literal_column("INTERVAL '+05:30'"), col))


def telegram_posts(user_id: uuid.UUID, since: datetime, until: datetime):
    """Posts read from Telegram (not the internal 'Pasted in chat' channel) in [since, until)."""
    return and_(Post.user_id == user_id, Post.posted_at >= since, Post.posted_at < until,
                Post.channel_id.in_(select(Channel.id).where(Channel.user_id == user_id, Channel.tg_chat_id != 0)))


async def raw_days(s: AsyncSession, user_id: uuid.UUID, since: datetime, until: datetime) -> dict[date, dict]:
    """Per India day, from the saved posts: {day: {posts, checked, fits: {verdict: n}}}."""
    where = telegram_posts(user_id, since, until)
    out: dict[date, dict] = {}

    def day(d: date) -> dict:
        return out.setdefault(d, {"posts": 0, "checked": 0, "fits": dict.fromkeys(FITS, 0)})

    for d, n in (await s.execute(select(ist_date(Post.posted_at), func.count()).where(where)
                                 .group_by(ist_date(Post.posted_at)))).all():
        day(d)["posts"] = n
    for d, n in (await s.execute(select(ist_date(Post.posted_at), func.count()).where(where, Post.stage == "scored")
                                 .group_by(ist_date(Post.posted_at)))).all():
        day(d)["checked"] = n
    fit_q = (select(ist_date(Post.posted_at), Job.verdict, func.count()).join(Post, Job.post_id == Post.id)
             .where(Job.user_id == user_id, Post.posted_at >= since, Post.posted_at < until,
                    Job.fit_score.is_not(None), Job.verdict.in_(FITS))
             .group_by(ist_date(Post.posted_at), Job.verdict))
    for d, verdict, n in (await s.execute(fit_q)).all():
        day(d)["fits"][verdict] = n
    return out


async def purge_old(s: AsyncSession, now: datetime) -> int:
    """Returns how many posts were removed (all users)."""
    cutoff, _ = report.day_bounds(now.astimezone(report.IST).date() - timedelta(days=KEEP_DAYS))
    users = (await s.execute(select(Post.user_id).where(Post.posted_at < cutoff).distinct())).scalars().all()
    removed = 0
    for user_id in users:
        done = set((await s.execute(select(DayStats.day).where(DayStats.user_id == user_id))).scalars())
        oldest = await s.scalar(select(func.min(Post.posted_at)).where(Post.user_id == user_id))
        for d, counts in (await raw_days(s, user_id, oldest, cutoff)).items():
            if d not in done:  # a day is summed once, before anything of it is removed
                s.add(DayStats(user_id=user_id, day=d, **counts))
        emailed = exists().where(Job.post_id == Post.id, Send.job_id == Job.id)
        result = await s.execute(delete(Post).where(Post.user_id == user_id, Post.posted_at < cutoff, ~emailed))
        removed += result.rowcount
        await s.commit()
    if removed:
        log.info("retention.posts_removed", count=removed)
    return removed
