"""Free daily token allowance: every AI call is recorded; the background pipeline pauses when every Groq model is
nearly used up (rolling 24 h, like Groq's own limit), keeping a reserve so the user's chat still works."""

import re
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import LlmLimit, LlmUsage
from app.db.session import get_sessionmaker
from app.llm import router

log = structlog.get_logger()
DAY = timedelta(hours=24)
_TPD = re.compile(r"tokens per day \(TPD\): Limit \d+, Used (\d+)", re.I)


def daily_used_from_error(message: str) -> int | None:
    """Groq's daily-limit error says how much the key has used: '... (TPD): Limit 200000, Used 199456, ...'."""
    m = _TPD.search(message)
    return int(m.group(1)) if m else None


async def sync_with_provider(s: AsyncSession, model: str, used: int, now: datetime | None = None,
                             expires_in: float | None = None) -> None:
    """Make our 24 h count at least the provider's own (usage from before Leapvoy counted, other apps on the key).
    expires_in: Groq's 'try again in …', the correction stops counting then (it is back-dated so it leaves the 24 h
    window at that moment); if Groq is still full, its next refusal corrects the count again."""
    now = now or datetime.now(UTC)
    missing = used - await used_24h(s, model, now)
    if missing > 0:
        at = now - DAY + timedelta(seconds=expires_in) if expires_in else now
        await record_with(s, model, missing, at)


async def note_limit(s: AsyncSession, model: str, message: str, now: datetime | None = None) -> None:
    """A model said 'limit reached': remember until when (its own 'try again in …'), and sync Groq's daily count."""
    now = now or datetime.now(UTC)
    daily = "per day" in message.lower()
    until = now + timedelta(seconds=router.retry_after(message))
    await s.execute(insert(LlmLimit).values(model=model, until=until, daily=daily)
                    .on_conflict_do_update(index_elements=["model"], set_={"until": until, "daily": daily}))
    await s.commit()
    if (used := daily_used_from_error(message)) is not None:
        await sync_with_provider(s, model, used, now, expires_in=router.retry_after(message))


async def _on_limit(model: str, message: str) -> None:
    async with get_sessionmaker()() as s:
        await note_limit(s, model, message)


async def record_with(s: AsyncSession, model: str, tokens: int, at: datetime | None = None) -> None:
    s.add(LlmUsage(model=model, tokens=tokens, at=at or datetime.now(UTC)))
    await s.commit()


async def record(model: str, tokens: int) -> None:
    async with get_sessionmaker()() as s:
        await record_with(s, model, tokens)


def install() -> None:
    """Call once per process (API, workers): the router reports tokens after each AI call, and limit errors."""
    router.on_usage = record
    router.on_limit = _on_limit


async def used_24h(s: AsyncSession, model: str, now: datetime) -> int:
    q = select(func.coalesce(func.sum(LlmUsage.tokens), 0)).where(LlmUsage.model == model, LlmUsage.at > now - DAY)
    return (await s.execute(q)).scalar_one()


async def background_allowed(s: AsyncSession, now: datetime) -> bool:
    """True while at least one Groq model still has more than the chat reserve left today."""
    settings = get_settings()
    await s.execute(delete(LlmUsage).where(LlmUsage.at < now - 2 * DAY))  # keep the table small
    groq = [m for m in dict.fromkeys([settings.llm_small, settings.llm_large, *settings.llm_fallbacks])
            if m.startswith("groq/")]
    cap = settings.groq_daily_tokens * (1 - settings.chat_reserve)
    for model in groq:
        if await used_24h(s, model, now) < cap:
            return True
    log.info("llm.background_paused_for_chat", reserve=settings.chat_reserve)
    return False
