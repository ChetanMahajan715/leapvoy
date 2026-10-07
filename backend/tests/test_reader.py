from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import func, select
from telethon.errors import FloodWaitError

from app.db.models import Post
from app.telegram import reader, store
from tests.conftest import requires_db

NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)


def msg(mid, text="Hiring ML Engineer, hr@zeta.ai"):
    return SimpleNamespace(id=mid, message=text, date=NOW)


class FakeClient:
    """Stands in for TelegramClient.iter_messages (the only network call reader uses)."""

    def __init__(self, messages, flood_after=None):
        self.messages = messages
        self.flood_after = flood_after  # raise FloodWait once after this many messages
        self.calls = []

    async def iter_messages(self, chat_id, min_id=0, reverse=False, offset_date=None):
        self.calls.append({"chat_id": chat_id, "min_id": min_id, "reverse": reverse, "offset_date": offset_date})
        for n, m in enumerate(x for x in self.messages if x.id > min_id):
            if self.flood_after is not None and n == self.flood_after:
                self.flood_after = None
                raise FloodWaitError(request=None, capture=7)
            yield m


# --- to_incoming -----------------------------------------------------------

def test_to_incoming_keeps_text():
    p = reader.to_incoming(msg(3, "AI Engineer role"))
    assert (p.tg_message_id, p.text, p.posted_at) == (3, "AI Engineer role", NOW)


def test_to_incoming_skips_messages_without_text():
    assert reader.to_incoming(msg(3, "")) is None
    assert reader.to_incoming(msg(3, None)) is None


# --- iter_posts ------------------------------------------------------------

async def collect(client, **kw):
    return [p async for p in reader.iter_posts(client, -1001, **kw)]


async def test_iter_posts_reads_after_cursor_oldest_first():
    client = FakeClient([msg(1), msg(2), msg(3)])
    posts = await collect(client, min_id=1, since=None)
    assert [p.tg_message_id for p in posts] == [2, 3]
    assert client.calls[0]["reverse"] is True and client.calls[0]["min_id"] == 1


async def test_iter_posts_waits_on_floodwait_and_resumes_without_dupes():
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    client = FakeClient([msg(1), msg(2), msg(3), msg(4)], flood_after=2)
    posts = await collect(client, min_id=0, since=None, sleep=fake_sleep)
    assert slept == [7]
    assert [p.tg_message_id for p in posts] == [1, 2, 3, 4]
    assert client.calls[1]["min_id"] == 2  # resumed after last message seen


async def test_iter_posts_skips_textless_but_moves_past_them():
    client = FakeClient([msg(1, ""), msg(2)])
    assert [p.tg_message_id for p in await collect(client, min_id=0, since=None)] == [2]


# --- catch_up + handle_new_message (real DB) -------------------------------

async def setup_user(sm, chat_ids=(-1001,), enabled=(-1001,)):
    async with sm() as s:
        uid = await store.get_or_create_user(s, "a@x.com")
        await store.upsert_channels(s, uid, [(c, f"ch{c}", None) for c in chat_ids])
        await store.set_enabled(s, uid, list(enabled), True)
    return uid


async def post_count(sm):
    async with sm() as s:
        return (await s.execute(select(func.count()).select_from(Post))).scalar_one()


@requires_db
async def test_catch_up_saves_enabled_channels_only(sm):
    uid = await setup_user(sm, chat_ids=(-1001, -1002), enabled=(-1001,))
    client = FakeClient([msg(1), msg(2)])
    assert await reader.catch_up(client, sm, uid) == 2
    assert [c["chat_id"] for c in client.calls] == [-1001]


@requires_db
async def test_catch_up_twice_is_idempotent_and_uses_cursor(sm):
    uid = await setup_user(sm)
    client = FakeClient([msg(1), msg(2)])
    await reader.catch_up(client, sm, uid)
    assert await reader.catch_up(client, sm, uid) == 0
    assert client.calls[1]["min_id"] == 2
    assert await post_count(sm) == 2


@requires_db
async def test_first_catch_up_only_looks_back_two_days(sm):
    uid = await setup_user(sm)
    client = FakeClient([])
    await reader.catch_up(client, sm, uid, now=NOW)
    assert client.calls[0]["offset_date"] == datetime(2026, 9, 27, 10, 0, tzinfo=UTC)


@requires_db
async def test_backfill_reads_from_start_since_date(sm):
    uid = await setup_user(sm)
    client = FakeClient([msg(5)])
    await reader.catch_up(client, sm, uid)  # cursor now 5
    since = datetime(2026, 7, 1, tzinfo=UTC)
    await reader.catch_up(client, sm, uid, since=since, from_start=True)
    assert client.calls[1]["min_id"] == 0 and client.calls[1]["offset_date"] == since


@requires_db
async def test_one_broken_channel_does_not_stop_others(sm):
    uid = await setup_user(sm, chat_ids=(-1001, -1002), enabled=(-1001, -1002))

    class HalfBroken(FakeClient):
        async def iter_messages(self, chat_id, **kw):
            if chat_id == -1001:  # listed first ("ch-1001" < "ch-1002")
                raise ValueError("Could not find the input entity")
            async for m in super().iter_messages(chat_id, **kw):
                yield m

    assert await reader.catch_up(HalfBroken([msg(1)]), sm, uid) == 1


@requires_db
async def test_live_message_saved_only_for_enabled_channel(sm):
    uid = await setup_user(sm, chat_ids=(-1001, -1002), enabled=(-1001,))
    assert await reader.handle_new_message(sm, uid, -1001, msg(10)) is True
    assert await reader.handle_new_message(sm, uid, -1002, msg(11)) is False  # disabled
    assert await reader.handle_new_message(sm, uid, -9999, msg(12)) is False  # unknown chat
    assert await reader.handle_new_message(sm, uid, -1001, msg(13, "")) is False  # no text
    assert await post_count(sm) == 1


@requires_db
async def test_live_message_not_saved_for_other_user(sm):
    await setup_user(sm)  # a@x.com has -1001 enabled
    async with sm() as s:
        other = await store.get_or_create_user(s, "b@x.com")
    assert await reader.handle_new_message(sm, other, -1001, msg(10)) is False



@requires_db
async def test_fetch_range_saves_one_old_day_and_keeps_the_cursor(sm):
    from datetime import timedelta

    uid = await setup_user(sm, chat_ids=(-1001,), enabled=(-1001,))
    day = NOW - timedelta(days=100)
    newest_first = [SimpleNamespace(id=900, message="today's post, hr@a.ai", date=NOW),
                    SimpleNamespace(id=12, message="old day B, hr@b.ai", date=day + timedelta(hours=5)),
                    SimpleNamespace(id=11, message="old day A, hr@c.ai", date=day + timedelta(hours=1)),
                    SimpleNamespace(id=10, message="day before, hr@d.ai", date=day - timedelta(hours=2))]

    class Client(FakeClient):  # Telegram: newest first, starting before offset_date
        async def iter_messages(self, chat_id, offset_date=None, **kw):
            for m in self.messages:
                if offset_date is None or m.date < offset_date:
                    yield m

    async with sm() as s:
        ch = await store.get_enabled_channel(s, uid, -1001)
        cursor = ch.last_message_id
    saved = await reader.fetch_range(Client(newest_first), sm, uid, day, day + timedelta(days=1))
    assert saved == 2
    async with sm() as s:
        texts = sorted((await s.execute(select(Post.text).where(Post.user_id == uid))).scalars())
        assert texts == ["old day A, hr@c.ai", "old day B, hr@b.ai"]
        assert (await store.get_enabled_channel(s, uid, -1001)).last_message_id >= cursor  # never moves back
