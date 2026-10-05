import pytest

from app.chat import store as chats
from app.telegram.store import get_or_create_user
from tests.conftest import requires_db
from tests.test_auth_api import api, bearer, secrets, signup  # noqa: F401 (fixtures)

pytestmark = requires_db


async def user_id(sm, email="me@x.com"):
    async with sm() as s:
        return await get_or_create_user(s, email)


async def add_chat(sm, uid, title, *messages):
    async with sm() as s:
        chat = await chats.create_chat(s, uid, title)
        for role, text in messages:
            await chats.add_message(s, uid, chat.id, role, text)
        return chat.id


async def test_new_chat_appears_in_the_list(api):
    t = await signup(api)
    r = await api.post("/chats", headers=bearer(t))
    assert r.status_code == 200 and r.json()["title"] == "New chat"
    listed = (await api.get("/chats", headers=bearer(t))).json()
    assert [c["id"] for c in listed] == [r.json()["id"]] and "updated_at" in listed[0]


async def test_list_is_newest_first_with_pinned_on_top(api, sm):
    t = await signup(api)
    uid = await user_id(sm)
    old = await add_chat(sm, uid, "Old", ("user", "hi"))
    new = await add_chat(sm, uid, "New", ("user", "hello"))
    await api.patch(f"/chats/{old}", headers=bearer(t), json={"pinned": True})
    assert [c["id"] for c in (await api.get("/chats", headers=bearer(t))).json()] == [old, new]


async def test_messages_come_back_in_order(api, sm):
    t = await signup(api)
    cid = await add_chat(sm, await user_id(sm), "Jobs", ("user", "show today's jobs"), ("assistant", "Here are 3 jobs."))
    msgs = (await api.get(f"/chats/{cid}/messages", headers=bearer(t))).json()
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "show today's jobs"), ("assistant", "Here are 3 jobs.")]


async def test_rename_and_delete(api, sm):
    t = await signup(api)
    cid = await add_chat(sm, await user_id(sm), "x")
    r = await api.patch(f"/chats/{cid}", headers=bearer(t), json={"title": "Allvest email"})
    assert r.json()["title"] == "Allvest email"
    assert (await api.delete(f"/chats/{cid}", headers=bearer(t))).status_code == 204
    assert (await api.get("/chats", headers=bearer(t))).json() == []


async def test_search_finds_words_in_titles_and_messages(api, sm):
    t = await signup(api)
    uid = await user_id(sm)
    a = await add_chat(sm, uid, "Allvest email", ("user", "write the email"))
    b = await add_chat(sm, uid, "Scheduling", ("user", "send the Rengy mail tomorrow"))
    await add_chat(sm, uid, "Other", ("user", "hello"))
    assert [c["id"] for c in (await api.get("/chats?q=rengy", headers=bearer(t))).json()] == [b]
    assert [c["id"] for c in (await api.get("/chats?q=allvest", headers=bearer(t))).json()] == [a]


async def test_users_never_see_each_others_chats(api, sm):
    a = await signup(api, "a@x.com")
    b = await signup(api, "b@x.com")
    cid = await add_chat(sm, await user_id(sm, "a@x.com"), "Private", ("user", "secret plans"))
    assert (await api.get("/chats", headers=bearer(b))).json() == []
    assert (await api.get(f"/chats/{cid}/messages", headers=bearer(b))).status_code == 404
    assert (await api.patch(f"/chats/{cid}", headers=bearer(b), json={"title": "hacked"})).status_code == 404
    assert (await api.delete(f"/chats/{cid}", headers=bearer(b))).status_code == 404
    assert (await api.get("/chats?q=secret", headers=bearer(b))).json() == []
    assert len((await api.get("/chats", headers=bearer(a))).json()) == 1


async def test_memories_can_be_listed_and_deleted_only_by_their_owner(api, sm):
    from app.db.models import Memory

    t = await signup(api, "me@x.com")
    other = await signup(api, "other@x.com")
    async with sm() as s:
        s.add(Memory(user_id=await user_id(sm, "me@x.com"), text="Prefer 10 AM"))
        await s.commit()
    [m] = (await api.get("/memories", headers=bearer(t))).json()
    assert m["text"] == "Prefer 10 AM" and (await api.get("/memories", headers=bearer(other))).json() == []
    assert (await api.delete(f"/memories/{m['id']}", headers=bearer(other))).status_code == 404
    assert (await api.delete(f"/memories/{m['id']}", headers=bearer(t))).status_code == 204
    assert (await api.get("/memories", headers=bearer(t))).json() == []
