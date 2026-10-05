""""What came in on <day>?": all posts of an India-time day, plus the jobs that fit the user's resume."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Post
from app.pipeline.store import PENDING

# ponytail: India only (no DST, so a fixed offset is exact); per-user time zones when other users need them
IST = timezone(timedelta(hours=5, minutes=30), "IST")


@dataclass
class DayReport:
    posts: list[Post]  # every post of the day, oldest first
    matches: list[tuple[Job, Post]]  # jobs that fit the resume (verdict ≠ SKIP), best score first
    pending: int  # posts of the day the AI hasn't finished yet


def day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time(0), IST)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def today() -> date:
    return datetime.now(IST).date()


def parse_day(text: str, now: date | None = None) -> date:
    """'today' | 'yesterday' | YYYY-MM-DD (the chat will accept free text via dateparser in Step 7)."""
    now = now or today()
    words = {"today": now, "yesterday": now - timedelta(days=1)}
    return words.get(text.strip().lower()) or date.fromisoformat(text)


async def day_report(s: AsyncSession, user_id: uuid.UUID, d: date) -> DayReport:
    start, end = day_bounds(d)
    in_day = (Post.user_id == user_id, Post.posted_at >= start, Post.posted_at < end)
    posts = (await s.execute(select(Post).where(*in_day).order_by(Post.posted_at))).scalars().all()
    matches = (
        await s.execute(
            select(Job, Post)
            .join(Post, Job.post_id == Post.id)
            .where(*in_day, Job.user_id == user_id, Job.fit_score.is_not(None), Job.verdict != "SKIP")
            .order_by(Job.fit_score.desc(), Job.id)
        )
    ).tuples().all()
    pending = (await s.execute(select(func.count()).where(*in_day, Post.stage.in_(PENDING)))).scalar_one()
    return DayReport(list(posts), list(matches), pending)
