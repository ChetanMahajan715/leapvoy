"""Stats: the funnel (posts read → checked → fit → sent → replies), fit breakdown, per email account, per India day.
Test-mode emails are counted apart so practice never inflates the real numbers."""

import uuid
from datetime import UTC, date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_db
from app.db.models import DayStats, SenderAccount, Send, User
from app.pipeline import report
from app.pipeline.posts import verdict_label
from app.pipeline.retention import FITS, ist_date, raw_days

router = APIRouter()


async def compute(s: AsyncSession, user_id: uuid.UUID, days: int = 7, now: datetime | None = None,
                  day: date | None = None) -> dict:
    """The last `days` India days (today included), or one India `day`."""
    now = now or datetime.now(UTC)
    today = now.astimezone(report.IST).date()
    if day is not None:
        first, days = day, 1
    else:
        first = today - timedelta(days=days - 1)
    since, _ = report.day_bounds(first)
    _, until = report.day_bounds(first + timedelta(days=days - 1))

    async def n(q) -> int:
        return (await s.execute(q)).scalar_one()

    # per day from the saved posts; a cleaned-up day (older than 30 days) uses its saved summary instead
    per_day = await raw_days(s, user_id, since, until)
    for row in (await s.execute(select(DayStats).where(DayStats.user_id == user_id, DayStats.day >= first,
                                                       DayStats.day <= first + timedelta(days=days - 1)))).scalars():
        per_day[row.day] = {"posts": row.posts, "checked": row.checked, "fits": row.fits}
    posts = sum(v["posts"] for v in per_day.values())
    checked = sum(v["checked"] for v in per_day.values())
    fit_rows = {f: sum(v["fits"].get(f, 0) for v in per_day.values()) for f in FITS}
    sent_in = and_(Send.user_id == user_id, Send.status == "sent", Send.sent_at >= since, Send.sent_at < until)
    real = and_(sent_in, Send.test_mode.is_(False))
    sent = await n(select(func.count()).select_from(Send).where(real))
    replies = await n(select(func.count()).select_from(Send).where(real, Send.replied_at.is_not(None)))
    test_sent = await n(select(func.count()).select_from(Send).where(sent_in, Send.test_mode.is_(True)))

    senders = []
    for acc in (await s.execute(select(SenderAccount).where(SenderAccount.user_id == user_id)
                                .order_by(SenderAccount.created_at, SenderAccount.id))).scalars():
        a_sent = await n(select(func.count()).select_from(Send).where(real, Send.sender_id == acc.id))
        a_rep = await n(select(func.count()).select_from(Send).where(real, Send.sender_id == acc.id,
                                                                     Send.replied_at.is_not(None)))
        senders.append({"email": acc.email, "sent": a_sent, "replies": a_rep,
                        "reply_rate": round(100 * a_rep / a_sent) if a_sent else 0})

    sent_days = dict((await s.execute(select(ist_date(Send.sent_at), func.count()).where(real)
                                      .group_by(ist_date(Send.sent_at)))).all())
    day_list = [first + timedelta(days=i) for i in range(days)]
    return {
        "days_back": days, "from": first.isoformat(), "to": (first + timedelta(days=days - 1)).isoformat(),
        "funnel": {"posts": posts, "checked": checked, "fit": sum(fit_rows.values()), "sent": sent, "replies": replies,
                   "reply_rate": round(100 * replies / sent) if sent else 0},
        "fit_breakdown": {verdict_label(v): fit_rows.get(v, 0) for v in FITS},
        "test_sent": test_sent,
        "senders": senders,
        "days": [{"date": d.isoformat(), "posts": per_day.get(d, {}).get("posts", 0), "sent": sent_days.get(d, 0)} for d in day_list],
    }


@router.get("/stats")
async def stats(days: int = 7, date: str | None = None, user: User = Depends(current_user),
                s: AsyncSession = Depends(get_db)):
    """?days=7|30|90, or ?date=today|yesterday|YYYY-MM-DD for one India day."""
    if date is not None:
        try:
            day = report.parse_day(date)
        except ValueError:
            raise HTTPException(422, "date must be today, yesterday or YYYY-MM-DD") from None
        return await compute(s, user.id, day=day)
    if days not in (7, 30, 90):
        raise HTTPException(422, "days must be 7, 30 or 90")
    return await compute(s, user.id, days)
