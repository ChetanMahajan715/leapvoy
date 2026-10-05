import base64
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Channel, TelegramAccount
from app.telegram import store
from app.telegram.store import IncomingPost
from tests.conftest import requires_db

pytestmark = requires_db
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)


@pytest.fixture
def master_key(monkeypatch):
    monkeypatch.setenv("MASTER_KEY", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://unused/x")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def post(mid, text="Hiring AI Engineer, mail hr@acme.ai"):
    return IncomingPost(tg_message_id=mid, text=text, posted_at=NOW)


async def user_with_channel(db, email="a@x.com", chat_id=-1001, enabled=True):
    uid = await store.get_or_create_user(db, email)
    await store.upsert_channels(db, uid, [(chat_id, "AI Jobs", "aijobs")])
    if enabled:
        await store.set_enabled(db, uid, [chat_id], True)
    return uid, await store.get_enabled_channel(db, uid, chat_id) if enabled else None


async def test_get_or_create_user_is_case_insensitive(db):
    assert await store.get_or_create_user(db, "Chetan@X.com") == await store.get_or_create_user(db, "chetan@x.com")


async def test_save_posts_inserts_and_moves_cursor(db):
    uid, ch = await user_with_channel(db)
    assert await store.save_posts(db, uid, ch.id, [post(5), post(7)]) == 2
    await db.refresh(ch)
    assert ch.last_message_id == 7


async def test_save_posts_twice_saves_nothing_new(db):
    uid, ch = await user_with_channel(db)
    await store.save_posts(db, uid, ch.id, [post(5), post(7)])
    assert await store.save_posts(db, uid, ch.id, [post(5), post(7)]) == 0


async def test_cursor_never_moves_back(db):
    uid, ch = await user_with_channel(db)
    await store.save_posts(db, uid, ch.id, [post(9)])
    await store.save_posts(db, uid, ch.id, [post(3)])  # backfill of an older post
    await db.refresh(ch)
    assert ch.last_message_id == 9


async def test_upsert_channels_keeps_enabled_and_cursor(db):
    uid, ch = await user_with_channel(db)
    await store.save_posts(db, uid, ch.id, [post(4)])
    await store.upsert_channels(db, uid, [(-1001, "AI Jobs (renamed)", None)])
    [again] = await store.list_channels(db, uid)
    assert (again.enabled, again.last_message_id, again.title) == (True, 4, "AI Jobs (renamed)")


async def test_users_never_see_each_others_channels(db):
    a, _ = await user_with_channel(db, "a@x.com", chat_id=-1001)
    b = await store.get_or_create_user(db, "b@x.com")
    assert await store.list_channels(db, b) == []
    assert await store.get_enabled_channel(db, b, -1001) is None
    assert await store.set_enabled(db, b, [-1001], False) == 0
    assert (await store.get_enabled_channel(db, a, -1001)) is not None


async def test_session_round_trip_is_encrypted(db, master_key):
    uid = await store.get_or_create_user(db, "a@x.com")
    await store.save_session(db, uid, "+911234567890", "1BVtsOK-secret-session")
    assert await store.load_session(db, uid) == "1BVtsOK-secret-session"
    raw = (await db.execute(select(TelegramAccount.session_enc))).scalar_one()
    assert b"secret-session" not in raw


async def test_delete_session(db, master_key):
    uid = await store.get_or_create_user(db, "a@x.com")
    await store.save_session(db, uid, "+91", "s")
    assert await store.users_with_telegram(db) == [uid]
    await store.delete_session(db, uid)
    assert await store.load_session(db, uid) is None
    assert await store.users_with_telegram(db) == []


async def test_list_channels_enabled_only(db):
    uid, _ = await user_with_channel(db, chat_id=-1001)
    await store.upsert_channels(db, uid, [(-1002, "Off channel", None)])
    assert [c.tg_chat_id for c in await store.list_channels(db, uid, enabled_only=True)] == [-1001]
    assert len(await store.list_channels(db, uid)) == 2
    assert all(isinstance(c, Channel) for c in await store.list_channels(db, uid))
