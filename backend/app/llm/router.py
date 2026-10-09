"""One entry point for structured LLM output, with free-tier fallback: primary Groq model → other models."""

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, TypeVar

import instructor
import litellm
import structlog
from instructor.core import InstructorRetryException
from instructor.core.exceptions import IncompleteOutputException
from pydantic import BaseModel

from app.core.config import Settings, get_settings

log = structlog.get_logger()
litellm.suppress_debug_info = True
T = TypeVar("T", bound=BaseModel)
Tier = Literal["small", "large"]

# errors where another model may still succeed (limits, outages, or output that never validated)
FALLBACK_ON = (
    litellm.RateLimitError,
    litellm.BadRequestError,  # e.g. Groq json_validate_failed / unsupported param on a fallback model
    litellm.APIConnectionError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
    litellm.Timeout,
    InstructorRetryException,
    IncompleteOutputException,  # the model ran out of output tokens mid-answer (seen 9 Oct): try the next one
)


class LLMUnavailable(RuntimeError):
    """Every configured model failed; the pipeline marks the post for retry."""


class RateLimited(LLMUnavailable):
    """Every model is at its free-tier per-minute limit even after waiting. Not a failure, try again later."""


class AIUnreachable(LLMUnavailable):
    """No model could be reached at all (no internet, provider servers down). Not the post's fault, retry later."""


# set by app.llm.usage.install(): told the tokens of every successful call (free daily allowance tracking)
on_usage: Callable[[str, int], Awaitable[None]] | None = None
on_limit: Callable[[str, str], Awaitable[None]] | None = None  # told each rate-limit error (Groq's daily "Used N")


async def _report(model: str, response) -> None:
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "total_tokens", None)
    if on_usage is None or not tokens:
        return
    try:
        await on_usage(model, tokens)
    except Exception:  # noqa: BLE001, bookkeeping must never break an answer
        log.warning("llm.usage_not_recorded", model=model, exc_info=True)


async def _limited(model: str, e: Exception) -> None:
    if on_limit is None:
        return
    try:
        await on_limit(model, str(e))
    except Exception:  # noqa: BLE001, bookkeeping must never break an answer
        log.warning("llm.limit_not_recorded", model=model, exc_info=True)


DEFAULT_WAIT = 10.0  # seconds, when Groq doesn't say how long
MAX_WAIT = 60.0
ROUNDS = 4  # wait-and-retry rounds when every model is rate-limited
_sleep = asyncio.sleep
_RETRY = re.compile(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", re.I)


def retry_after(message: str) -> float:
    """Groq says e.g. 'Please try again in 1.8075s' / '922.5ms' / '1m2.5s'."""
    m = _RETRY.search(message)
    if not m:
        return DEFAULT_WAIT
    minutes, value, unit = m.groups()
    seconds = float(value) / (1000 if unit.lower() == "ms" else 1)
    return seconds + 60 * int(minutes or 0)


_UNREACHABLE = re.compile(r"Cannot connect to host|getaddrinfo|Connection(Error| refused| reset)|APIConnectionError|"
                          r"InternalServerError|ServiceUnavailable|50[234]|Timeout|timed out", re.I)


def _is_unreachable(e: Exception) -> bool:
    """Network down or the provider's servers failing, nothing to do with what we asked."""
    return isinstance(e, (litellm.APIConnectionError, litellm.InternalServerError, litellm.ServiceUnavailableError,
                          litellm.Timeout)) or bool(_UNREACHABLE.search(f"{type(e).__name__} {e}"))


def _is_rate_limit(e: Exception) -> bool:
    # Instructor wraps provider errors in InstructorRetryException, so check the text too
    return isinstance(e, litellm.RateLimitError) or "rate_limit" in str(e).lower() or "RateLimitError" in str(e)


@lru_cache
def _client() -> instructor.AsyncInstructor:
    return instructor.from_litellm(litellm.acompletion, mode=instructor.Mode.JSON_SCHEMA)  # gpt-oss breaks TOOLS mode on Groq


async def _create(**kwargs):
    result, completion = await _client().create_with_completion(**kwargs)
    await _report(kwargs["model"], completion)
    return result


def _auth(model: str, s: Settings) -> dict | None:
    """Credentials for a model, or None if its provider isn't configured."""
    provider = model.split("/", 1)[0]
    if provider == "groq":
        return {"api_key": s.groq_api_key} if s.groq_api_key else None
    if provider == "mistral":
        return {"api_key": s.mistral_api_key} if s.mistral_api_key else None
    if provider == "gemini":
        return {"api_key": s.gemini_api_key} if s.gemini_api_key else None
    if provider == "ollama":
        return {"api_base": s.ollama_url} if s.ollama_url else None
    return None


def candidates(tier: Tier, s: Settings, prefer: str | None = None) -> list[str]:
    """Models to try in order. prefer = the user's pick (model picker): tried first, the rest stay as backup."""
    first = s.llm_small if tier == "small" else s.llm_large
    ordered = dict.fromkeys([*([prefer] if prefer else []), first, *s.llm_fallbacks])  # dedupe, keep order
    return [m for m in ordered if _auth(m, s) is not None]


async def structured(
    tier: Tier, messages: list[dict], response_model: type[T], temperature: float = 0.2, max_retries: int = 2,
    prefer: str | None = None,
) -> T:
    s = get_settings()
    last: Exception | None = None
    for _ in range(ROUNDS):
        waits: list[float] = []  # one entry per model that was only rate-limited
        unreachable = 0
        tried = candidates(tier, s, prefer)
        for model in tried:
            extra = {"reasoning_effort": "low" if tier == "small" else "medium"} if "gpt-oss" in model else {}
            try:
                return await _create(
                    model=model,
                    messages=messages,
                    response_model=response_model,
                    temperature=temperature,
                    max_retries=max_retries,
                    **_auth(model, s),
                    **extra,
                )
            except FALLBACK_ON as e:
                limited = _is_rate_limit(e)
                log.warning("llm.fallback", model=model, error=type(e).__name__, rate_limited=limited)
                last = e
                if limited:
                    waits.append(retry_after(str(e)))
                    await _limited(model, e)
                elif _is_unreachable(e):
                    unreachable += 1
        if not waits and tried and unreachable == len(tried):  # no internet / every provider down
            raise AIUnreachable(f"No AI provider reachable for tier={tier}") from last
        if not waits:  # real failures, not limits → waiting won't help
            raise LLMUnavailable(f"All models failed for tier={tier}") from last
        wait = min(min(waits) + 0.5, MAX_WAIT)  # free tier resets per minute; wait for the soonest model
        log.info("llm.rate_limited_wait", tier=tier, seconds=round(wait, 1))
        await _sleep(wait)
    raise RateLimited(f"Free-tier limits still busy for tier={tier}") from last


# --- streaming chat with tool calling (the chat assistant) -----------------------------------

@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text


class ToolCallAccumulator:
    """Streams deliver a tool call in pieces (name first, JSON arguments in chunks), keyed by index."""

    def __init__(self) -> None:
        self._parts: dict[int, dict[str, str]] = {}

    def add(self, piece) -> None:
        part = self._parts.setdefault(piece.index or 0, {"id": "", "name": "", "arguments": ""})
        if piece.id:
            part["id"] = piece.id
        if piece.function and piece.function.name:
            part["name"] = piece.function.name
        if piece.function and piece.function.arguments:
            part["arguments"] += piece.function.arguments

    def calls(self) -> list[ToolCall]:
        return [ToolCall(p["id"] or f"call_{i}", p["name"], p["arguments"] or "{}")
                for i, p in sorted(self._parts.items()) if p["name"]]


async def stream_chat(
    tier: Tier, messages: list[dict], tools: list[dict], prefer: str | None = None
) -> AsyncIterator[tuple[str, object]]:
    """Yields ("text", str) pieces as they arrive, ("model", id) of the model that answered, then
    ("tool_calls", [ToolCall]) if the model wants tools.
    Falls back to the next model only if one fails before saying anything; waits out rate limits."""
    s = get_settings()
    last: Exception | None = None
    for _ in range(ROUNDS):
        waits: list[float] = []
        for model in candidates(tier, s, prefer):
            extra = {"reasoning_effort": "low"} if "gpt-oss" in model else {}
            started, acc, final = False, ToolCallAccumulator(), None
            try:
                response = await litellm.acompletion(model=model, messages=messages, tools=tools, stream=True,
                                                     temperature=0.3, stream_options={"include_usage": True},
                                                     **_auth(model, s), **extra)
                async for chunk in response:
                    if getattr(chunk, "usage", None):
                        final = chunk  # the last chunk carries the token count
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        started = True
                        yield "text", delta.content
                    for piece in delta.tool_calls or []:
                        acc.add(piece)
            except FALLBACK_ON as e:
                if started:  # half an answer is already on screen, don't restart with another model
                    raise LLMUnavailable(f"{model} stopped mid-answer") from e
                log.warning("llm.fallback", model=model, error=type(e).__name__, rate_limited=_is_rate_limit(e))
                last = e
                if _is_rate_limit(e):
                    waits.append(retry_after(str(e)))
                    await _limited(model, e)
                continue
            await _report(model, final)
            yield "model", model
            if calls := acc.calls():
                yield "tool_calls", calls
            return
        if not waits:
            raise LLMUnavailable(f"All models failed for tier={tier}") from last
        await _sleep(min(min(waits) + 0.5, MAX_WAIT))
    raise RateLimited(f"Free-tier limits still busy for tier={tier}") from last
