"""The model picker: every configured AI model with a friendly name and its free usage today."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import LlmLimit
from app.llm import router, usage

# id → (label, maker, note). Order of the picker = Leapvoy's own fallback order.
CATALOG = {
    "groq/openai/gpt-oss-20b": ("GPT-OSS 20B", "OpenAI · on Groq", "Fastest: chat, reading posts"),
    "groq/openai/gpt-oss-120b": ("GPT-OSS 120B", "OpenAI · on Groq", "Smartest: fit checks, emails"),
    "groq/qwen/qwen3.8-27b": ("Qwen 3.8 27B", "Alibaba · on Groq", "Very fast backup"),
    "mistral/ministral-14b-latest": ("Ministral 14B", "Mistral", "Backup when Groq's day is used up"),
    "gemini/gemini-3.8-flash": ("Gemini 3.8 Flash", "Google", "Newest Gemini, sometimes overloaded"),
    "gemini/gemini-3.5-flash": ("Gemini 3.5 Flash", "Google", "Steady, a bit slower"),
    "ollama/ministral-3b": ("Ministral 3B (local)", "On your server", "Last resort, offline"),
}


def available(s: Settings | None = None) -> list[str]:
    """Configured models, best-first (the same order Leapvoy falls back in)."""
    s = s or get_settings()
    ordered = dict.fromkeys([s.llm_small, s.llm_large, *s.llm_fallbacks])
    return [m for m in ordered if router._auth(m, s) is not None]


def label(model: str) -> str:
    return CATALOG.get(model, (model.split("/")[-1],))[0]


async def list_models(s: AsyncSession, now: datetime) -> list[dict]:
    settings = get_settings()
    limits = {x.model: x for x in (await s.execute(select(LlmLimit))).scalars()}
    out = []
    for model in available(settings):
        name, maker, note = CATALOG.get(model, (label(model), model.split("/")[0].title(), ""))
        used = await usage.used_24h(s, model, now)
        cap = settings.groq_daily_tokens if model.startswith("groq/") else None  # others don't publish free limits
        left = None if cap is None else max(0, round(100 - used * 100 / cap))
        noted = limits.get(model)
        blocked = noted if noted and noted.until > now else None
        coming_back = bool(noted and noted.daily and noted.until <= now)  # Groq's own wait is over: some usage is back
        if (blocked and (blocked.daily or cap is None)) or (left == 0 and not coming_back):
            state, left = "empty", 0 if cap else None  # "No usage left (, back at …)"
        elif blocked:
            state = "busy"  # per-minute limit: usable again in seconds
        elif left is not None and left < 20:
            state = "low"
        else:
            state = "ok"
        out.append({"id": model, "label": name, "maker": maker, "note": note, "used_today": used,
                    "left_pct": left, "state": state, "back_at": blocked.until.isoformat() if blocked else None})
    return out
