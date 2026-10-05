import litellm
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.llm import router
from app.llm.schemas import ExtractedPost, FitCheck


def settings(**kw):
    # explicit: litellm loads ../.env into the process on import, so real optional keys would leak in
    return Settings(**{"database_url": "x", "groq_api_key": "gsk_test", "mistral_api_key": None, "gemini_api_key": None, "ollama_url": None,
                       "_env_file": None, **kw})


@pytest.fixture
def calls(monkeypatch):
    """Record which models were tried; models listed in `fail` raise a rate-limit error."""
    log = {"tried": [], "fail": set(), "kwargs": []}

    async def fake_create(**kw):
        log["tried"].append(kw["model"])
        log["kwargs"].append(kw)
        if kw["model"] in log["fail"]:
            raise litellm.RateLimitError("429", llm_provider="groq", model=kw["model"])
        return kw["response_model"](jobs=[])

    monkeypatch.setattr(router, "_create", fake_create)
    return log


MSG = [{"role": "user", "content": "x"}]


def test_candidates_skip_providers_without_keys():
    s = settings()
    # every Groq model has its own free limit: try all three before waiting (fastest first after the main one)
    assert router.candidates("small", s) == ["groq/openai/gpt-oss-20b", "groq/qwen/qwen3.8-27b", "groq/openai/gpt-oss-120b"]
    assert router.candidates("large", s) == ["groq/openai/gpt-oss-120b", "groq/qwen/qwen3.8-27b", "groq/openai/gpt-oss-20b"]
    full = router.candidates("small", settings(mistral_api_key="m", gemini_api_key="g", ollama_url="http://ollama:11434"))
    # after the 3 Groq models: Mistral's free-plan model, then Gemini, then a local model
    assert full[3:] == ["mistral/ministral-14b-latest", "gemini/gemini-3.8-flash", "gemini/gemini-3.5-flash", "ollama/ministral-3b"]


async def test_small_tier_uses_small_model_with_low_temperature(calls, monkeypatch):
    monkeypatch.setattr(router, "get_settings", settings)
    await router.structured("small", MSG, ExtractedPost)
    assert calls["tried"] == ["groq/openai/gpt-oss-20b"]
    assert calls["kwargs"][0]["temperature"] <= 0.3
    assert calls["kwargs"][0]["api_key"] == "gsk_test"


async def test_falls_back_on_rate_limit(calls, monkeypatch):
    monkeypatch.setattr(router, "get_settings", settings)
    calls["fail"] = {"groq/openai/gpt-oss-120b"}
    await router.structured("large", MSG, ExtractedPost)
    assert calls["tried"] == ["groq/openai/gpt-oss-120b", "groq/qwen/qwen3.8-27b"]


async def test_raises_when_every_model_fails(calls, monkeypatch):
    monkeypatch.setattr(router, "get_settings", settings)
    calls["fail"] = set(router.candidates("small", settings()))
    with pytest.raises(router.LLMUnavailable):
        await router.structured("small", MSG, ExtractedPost)


def test_retry_wait_is_read_from_groq_message():
    assert router.retry_after("Please try again in 1.8075s. Need more") == 1.8075
    assert router.retry_after("Please try again in 922.5ms.") == 0.9225
    assert router.retry_after("Please try again in 1m2.5s.") == 62.5
    assert router.retry_after("something else") == router.DEFAULT_WAIT


async def test_waits_and_retries_when_every_model_is_rate_limited(calls, monkeypatch):
    monkeypatch.setattr(router, "get_settings", settings)
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        calls["fail"] = set()  # the limit resets after waiting

    monkeypatch.setattr(router, "_sleep", fake_sleep)
    calls["fail"] = set(router.candidates("small", settings()))
    await router.structured("small", MSG, ExtractedPost)
    assert slept and calls["tried"][-1] == "groq/openai/gpt-oss-20b"


async def test_gives_up_with_rate_limited_after_max_rounds(calls, monkeypatch):
    monkeypatch.setattr(router, "get_settings", settings)
    monkeypatch.setattr(router, "_sleep", lambda s: __import__("asyncio").sleep(0))
    calls["fail"] = set(router.candidates("small", settings()))
    with pytest.raises(router.RateLimited):
        await router.structured("small", MSG, ExtractedPost)


def test_fit_schema_rejects_bad_values():
    ok = dict(score=80, rows=[], verdict="APPLY", role_family="target", matched_skills=[], gaps=[], flags=[])
    FitCheck(**ok)
    with pytest.raises(ValidationError):
        FitCheck(**{**ok, "score": 101})
    with pytest.raises(ValidationError):
        FitCheck(**{**ok, "verdict": "YES PLEASE"})


async def test_no_internet_is_ai_unreachable_not_a_failure(monkeypatch):
    """1 Oct: the laptop lost internet → every provider 'Cannot connect to host' → posts must not be blamed."""
    monkeypatch.setattr(router, "get_settings", settings)

    async def offline(**kw):
        raise litellm.InternalServerError("GroqException - Cannot connect to host api.groq.com:443 [getaddrinfo failed]",
                                          llm_provider="groq", model=kw["model"])

    monkeypatch.setattr(router, "_create", offline)
    with pytest.raises(router.AIUnreachable):
        await router.structured("small", MSG, ExtractedPost)


async def test_bad_answers_are_still_a_real_failure(monkeypatch):
    monkeypatch.setattr(router, "get_settings", settings)

    async def bad(**kw):
        raise litellm.BadRequestError("json_validate_failed", llm_provider="groq", model=kw["model"])

    monkeypatch.setattr(router, "_create", bad)
    with pytest.raises(router.LLMUnavailable) as e:
        await router.structured("small", MSG, ExtractedPost)
    assert not isinstance(e.value, router.AIUnreachable)
