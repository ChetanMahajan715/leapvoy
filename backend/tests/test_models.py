"""Model picker: the chosen model goes first (others stay as backup), and every model shows its free usage left."""
from datetime import timedelta

from app.core.config import get_settings
from app.llm import models, router, usage
from tests.conftest import requires_db
from tests.test_auth_api import api, bearer, secrets, signup  # noqa: F401 (fixtures)
from tests.test_llm_router import settings
from tests.test_pipeline import NOW

GROQ_20B = "groq/openai/gpt-oss-20b"
TPD = ("Rate limit reached for model `openai/gpt-oss-20b` on tokens per day (TPD): Limit 200000, Used 199800, "
       "Requested 3000. Please try again in 21m30s.")


def test_chosen_model_goes_first_and_the_rest_stay_as_backup():
    s = settings(mistral_api_key="m")
    order = router.candidates("small", s, prefer="mistral/ministral-14b-latest")
    assert order[0] == "mistral/ministral-14b-latest" and GROQ_20B in order[1:]
    assert router.candidates("small", s, prefer="gemini/gemini-3.8-flash")[0] == GROQ_20B  # not set up → ignored


@requires_db
async def test_usage_left_and_no_usage_left(sm):
    async with sm() as s:
        await usage.record_with(s, GROQ_20B, 50_000, NOW)
        [m] = [x for x in await models.list_models(s, NOW) if x["id"] == GROQ_20B]
        assert m["left_pct"] == 75 and m["state"] == "ok" and m["label"] == "GPT-OSS 20B"
        await usage.note_limit(s, GROQ_20B, TPD, NOW)  # Groq said: daily limit reached
        [m] = [x for x in await models.list_models(s, NOW) if x["id"] == GROQ_20B]
        assert m["state"] == "empty" and m["left_pct"] == 0
        assert m["back_at"] == (NOW + timedelta(minutes=21, seconds=30)).isoformat()
        [m] = [x for x in await models.list_models(s, NOW + timedelta(minutes=22)) if x["id"] == GROQ_20B]
        assert m["state"] != "empty"  # the wait is over


@requires_db
async def test_models_api_lists_every_configured_model(api):
    t = await signup(api)
    r = (await api.get("/models", headers=bearer(t))).json()
    ids = [m["id"] for m in r["models"]]
    assert GROQ_20B in ids and "groq/openai/gpt-oss-120b" in ids and r["auto"] == get_settings().llm_small
    assert all({"label", "maker", "note", "state", "used_today"} <= set(m) for m in r["models"])


@requires_db
async def test_fully_used_groq_model_says_no_usage_left_even_before_groq_refuses(sm):
    async with sm() as s:
        await usage.record_with(s, GROQ_20B, 200_000, NOW)
        [m] = [x for x in await models.list_models(s, NOW) if x["id"] == GROQ_20B]
        assert m["state"] == "empty" and m["left_pct"] == 0
