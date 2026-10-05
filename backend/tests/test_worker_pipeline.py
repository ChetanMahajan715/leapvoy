from datetime import timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import LlmUsage, Post
from app.llm import usage
from app.workers import pipeline as worker
from tests.conftest import requires_db
from tests.test_pipeline import AI_POST, NOW, llm, make_posts, match  # noqa: F401 (fixtures)

pytestmark = requires_db
GROQ = ["groq/openai/gpt-oss-20b", "groq/qwen/qwen3.8-27b", "groq/openai/gpt-oss-120b"]


async def stage(sm, pid):
    async with sm() as s:
        return (await s.get(Post, pid)).stage


async def test_background_only_checks_recent_posts_never_old_backlog(sm, llm, match):
    _, [pid] = await make_posts(sm, [AI_POST])  # posted at NOW
    assert await worker.run_round(sm, NOW + timedelta(days=worker.RECENT_DAYS + 1)) == {}  # too old: left alone
    assert await stage(sm, pid) == "new" and llm.calls == []
    await worker.run_round(sm, NOW + timedelta(hours=2))
    assert await stage(sm, pid) == "scored"


async def use(sm, model, tokens, at):
    async with sm() as s:
        s.add(LlmUsage(model=model, tokens=tokens, at=at))
        await s.commit()


async def test_background_pauses_when_every_groq_model_is_nearly_used_up(sm, llm, match):
    """Keeps a reserve of the free daily tokens for the user's chat."""
    _, [pid] = await make_posts(sm, [AI_POST])
    almost = int(get_settings().groq_daily_tokens * 0.85)
    for m in GROQ:
        await use(sm, m, almost, NOW)
    assert await worker.run_round(sm, NOW + timedelta(hours=1)) == {"paused": 1}
    assert await stage(sm, pid) == "new" and llm.calls == []


async def test_usage_older_than_a_day_no_longer_counts(sm):
    for m in GROQ:
        await use(sm, m, 10**6, NOW - timedelta(hours=25))
    async with sm() as s:
        assert await usage.background_allowed(s, NOW)
        await use(sm, GROQ[0], 500, NOW)
        assert await usage.used_24h(s, GROQ[0], NOW) == 500


async def test_router_reports_tokens_used(sm, monkeypatch):
    seen = []

    async def hook(model, tokens):
        seen.append((model, tokens))

    from types import SimpleNamespace

    from app.llm import router

    monkeypatch.setattr(router, "on_usage", hook)
    await router._report("groq/openai/gpt-oss-20b", SimpleNamespace(usage=SimpleNamespace(total_tokens=1234)))
    await router._report("groq/openai/gpt-oss-20b", SimpleNamespace(usage=None))  # unknown → not reported
    assert seen == [("groq/openai/gpt-oss-20b", 1234)]
    async with sm() as s:
        await usage.record_with(s, "groq/openai/gpt-oss-20b", 1234, NOW)
        assert (await s.execute(select(LlmUsage.tokens))).scalar_one() == 1234


TPD = ('litellm.RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` '
       'in organization `org_x` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199456, '
       'Requested 3595. Please try again in 21m58.032s."}}')


def test_groq_daily_usage_is_read_from_its_error():
    assert usage.daily_used_from_error(TPD) == 199456
    assert usage.daily_used_from_error("tokens per minute (TPM): Limit 8000, Used 7000") is None
    assert usage.daily_used_from_error("something else") is None


async def test_groqs_own_count_corrects_ours_so_the_reserve_works_from_the_start(sm):
    """Usage from before Leapvoy started counting still counts: Groq's 'Used N' becomes our total."""
    async with sm() as s:
        await usage.record_with(s, "groq/openai/gpt-oss-20b", 5000, NOW)
        await usage.sync_with_provider(s, "groq/openai/gpt-oss-20b", 199456, NOW)
        assert await usage.used_24h(s, "groq/openai/gpt-oss-20b", NOW) == 199456
        await usage.sync_with_provider(s, "groq/openai/gpt-oss-20b", 1000, NOW)  # never lowers our count
        assert await usage.used_24h(s, "groq/openai/gpt-oss-20b", NOW) == 199456


async def test_round_stops_at_the_first_rate_limit_instead_of_hammering(sm, llm, match, monkeypatch):
    _, pids = await make_posts(sm, [AI_POST, AI_POST + " 2", AI_POST + " 3"])
    tried = []

    async def limited(sm_, post_id):
        tried.append(post_id)
        return "rate_limited"

    monkeypatch.setattr(worker.graph, "run_post", limited)
    assert await worker.run_round(sm, NOW + timedelta(hours=1)) == {"rate_limited": 1}
    assert tried == pids[:1]  # the other two wait for the next round


async def test_groqs_correction_expires_when_groq_says_usage_comes_back(sm):
    """Groq: 'Used 199456 … try again in 20m' → after 20 minutes Leapvoy tries again (Groq re-corrects if still full)."""
    async with sm() as s:
        await usage.record_with(s, "groq/openai/gpt-oss-20b", 5000, NOW - timedelta(hours=1))
        await usage.note_limit(s, "groq/openai/gpt-oss-20b", TPD.replace("21m58.032s", "20m0s"), NOW)
        assert await usage.used_24h(s, "groq/openai/gpt-oss-20b", NOW) == 199456
        later = NOW + timedelta(minutes=20, seconds=1)
        assert await usage.used_24h(s, "groq/openai/gpt-oss-20b", later) == 5000  # only what Leapvoy itself used
