import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.api.deps import get_sm
from app.chat import agent
from app.db.models import Chat, Memory, Message, PendingAction, Send
from app.llm import router
from app.main import app
from tests.conftest import requires_db
from tests.test_auth_api import PW, api, bearer, secrets  # noqa: F401 (fixtures)
from tests.test_outbox import setup, smtp  # noqa: F401 (fixtures)

pytestmark = requires_db


class FakeAI:
    """Scripted model: each round is a list of ("text", str) / ("tool_calls", [...]) events."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.seen: list[list[dict]] = []
        self.prefer: list[str | None] = []

    async def __call__(self, tier, messages, tools, prefer=None):
        self.seen.append(list(messages))
        self.prefer.append(prefer)
        for event in self.rounds.pop(0) if self.rounds else [("text", "ok")]:
            yield event


def call(name, **args):
    return ("tool_calls", [router.ToolCall(id=f"c_{name}", name=name, arguments=json.dumps(args))])


@pytest.fixture
def ai(monkeypatch, sm):
    app.dependency_overrides[get_sm] = lambda: sm

    def use(*rounds):
        fake = FakeAI(*rounds)
        monkeypatch.setattr(agent, "stream_chat", fake)
        return fake

    async def fake_title(text):
        return "Test title"

    monkeypatch.setattr(agent, "make_title", fake_title)
    yield use
    app.dependency_overrides.pop(get_sm, None)


async def chat(api, h, message, **body):
    r = await api.post("/chat/stream", headers=h, json={"message": message, **body})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def text_of(events):
    return "".join(e["text"] for e in events if e["type"] == "text")


async def signed_in(api, db, email="a@x.com"):
    uid, jobs = await setup(db, email=email)
    r = await api.post("/auth/signup", json={"email": email, "password": PW, "device_name": "t"})
    return uid, jobs, bearer(r.json())


async def n(db, model):
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


# --- streaming + saving -------------------------------------------------------------------

async def test_reply_streams_and_the_chat_is_saved_with_a_title(api, db, smtp, ai):
    _, _, h = await signed_in(api, db)
    ai([("text", "Hello "), ("text", "Chetan!")])
    events = await chat(api, h, "hi")
    assert events[0]["type"] == "chat" and text_of(events) == "Hello Chetan!" and events[-1]["type"] == "done"
    [c] = (await api.get("/chats", headers=h)).json()
    assert c["title"] == "Test title"
    msgs = (await api.get(f"/chats/{c['id']}/messages", headers=h)).json()
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "hi"), ("assistant", "Hello Chetan!")]


async def test_tool_call_adds_a_card_then_the_model_answers(api, db, smtp, ai):
    _, jobs, h = await signed_in(api, db)
    fake = ai([call("list_jobs", date="2026-09-30")], [("text", "Here is 1 job.")])
    events = await chat(api, h, "show jobs from 30 sep")
    cards = [{k: v for k, v in e["card"].items() if k != "note"} for e in events if e["type"] == "card"]
    assert cards == [{"type": "jobs", "date": "2026-09-30", "job_ids": jobs}] and text_of(events) == "Here is 1 job."
    assert fake.seen[1][-1]["role"] == "tool" and "Company0" in fake.seen[1][-1]["content"]  # AI saw the result


async def test_send_request_only_shows_a_confirm_card(api, db, smtp, ai):
    _, [job], h = await signed_in(api, db)
    ai([call("schedule_email", job_id=job, when="tomorrow 10am")], [("text", "Tap Confirm to schedule it.")])
    events = await chat(api, h, f"send job {job} tomorrow 10 am")
    assert [e["card"]["type"] for e in events if e["type"] == "card"] == ["confirm"]
    assert await n(db, Send) == 0 and await n(db, PendingAction) == 1


async def test_follow_up_message_continues_the_same_chat_with_history(api, db, smtp, ai):
    _, _, h = await signed_in(api, db)
    ai([("text", "First answer")])
    first = await chat(api, h, "first question")
    fake = ai([("text", "Second answer")])
    await chat(api, h, "second question", chat_id=first[0]["chat_id"])
    roles = [(m["role"], m["content"]) for m in fake.seen[0][1:]]
    assert roles == [("user", "first question"), ("assistant", "First answer"), ("user", "second question")]
    assert await n(db, Chat) == 1


async def test_incognito_saves_nothing(api, db, smtp, ai):
    _, _, h = await signed_in(api, db)
    ai([call("remember", fact="prefer 10 AM")], [("text", "Not saved in incognito.")])
    events = await chat(api, h, "remember I prefer 10 AM", incognito=True,
                        history=[{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}])
    assert text_of(events) == "Not saved in incognito."
    assert await n(db, Chat) == 0 and await n(db, Message) == 0 and await n(db, Memory) == 0


async def test_incognito_history_keeps_what_the_cards_showed(api, db, smtp, ai):
    _, _, h = await signed_in(api, db)
    fake = ai([("text", "ok")])
    await chat(api, h, "send the first one", incognito=True, history=[
        {"role": "user", "content": "jobs?"},
        {"role": "assistant", "content": "1 job.", "cards": [{"type": "jobs", "note": "#14 fit 81/100: Allvest"}]}])
    assert "#14 fit 81/100: Allvest" in fake.seen[0][2]["content"]  # the AI still knows the job id


async def test_memories_are_given_to_the_ai(api, db, smtp, ai):
    uid, _, h = await signed_in(api, db)
    db.add(Memory(user_id=uid, text="Prefer sending at 10 AM"))
    await db.commit()
    fake = ai([("text", "ok")])
    await chat(api, h, "hello")
    assert "Prefer sending at 10 AM" in fake.seen[0][0]["content"]


async def test_cannot_post_into_someone_elses_chat(api, db, smtp, ai):
    _, _, a = await signed_in(api, db, "a@x.com")
    ai([("text", "x")])
    cid = (await chat(api, a, "mine"))[0]["chat_id"]
    b = bearer((await api.post("/auth/signup", json={"email": "b@x.com", "password": PW, "device_name": "t"})).json())
    r = await api.post("/chat/stream", headers=b, json={"message": "hi", "chat_id": cid})
    assert r.status_code == 404


async def test_ai_failure_becomes_a_friendly_error_event(api, db, smtp, ai, monkeypatch):
    _, _, h = await signed_in(api, db)

    async def broken(tier, messages, tools, prefer=None):
        raise router.LLMUnavailable("down")
        yield  # pragma: no cover

    monkeypatch.setattr(agent, "stream_chat", broken)
    events = await chat(api, h, "hi")
    assert events[-1]["type"] == "error" and "busy" in events[-1]["message"]


# --- assembling tool calls from stream pieces ---------------------------------------------

def test_tool_call_pieces_are_joined():
    def piece(index, id=None, name=None, args=None):
        fn = SimpleNamespace(name=name, arguments=args)
        return SimpleNamespace(index=index, id=id, function=fn)

    acc = router.ToolCallAccumulator()
    for p in [piece(0, "c1", "schedule_email", '{"job_id":'), piece(0, None, None, ' 14, "when": "now"}'),
              piece(1, "c2", "stats", "{}")]:
        acc.add(p)
    assert [(c.id, c.name, json.loads(c.arguments)) for c in acc.calls()] == [
        ("c1", "schedule_email", {"job_id": 14, "when": "now"}), ("c2", "stats", {})]


async def test_repeated_identical_tool_call_runs_once_and_shows_one_card(api, db, smtp, ai):
    _, [job], h = await signed_in(api, db)
    fake = ai([call("write_email", job_id=job)], [call("write_email", job_id=job)], [call("write_email", job_id=job)],
              [("text", "Your email is ready.")])
    events = await chat(api, h, "write the email for it")
    assert [e["card"]["type"] for e in events if e["type"] == "card"] == ["draft"]
    assert text_of(events) == "Your email is ready."
    assert "already did" in fake.seen[2][-1]["content"]  # the AI was told to stop repeating


async def test_chosen_model_is_used_and_who_answered_is_shown(api, db, smtp, ai):
    _, _, h = await signed_in(api, db)
    fake = ai([("model", "mistral/ministral-14b-latest"), ("text", "Hi")])
    events = await chat(api, h, "hi", model="mistral/ministral-14b-latest")
    assert fake.prefer == ["mistral/ministral-14b-latest"]
    assert {"type": "model", "model": "mistral/ministral-14b-latest", "label": "Ministral 14B"} in events


async def test_unknown_model_is_refused(api, db, smtp, ai):
    _, _, h = await signed_in(api, db)
    r = await api.post("/chat/stream", headers=h, json={"message": "hi", "model": "openai/gpt-5"})
    assert r.status_code == 400


async def test_each_tool_says_what_it_is_doing_before_it_runs(api, db, smtp, ai):
    """Long steps (reading Telegram can take a minute) show a live status line instead of an endless spinner."""
    _, _, h = await signed_in(api, db)
    ai([call("stats", days=7)], [("text", "Here are your numbers.")])
    events = await chat(api, h, "how am I doing")
    kinds = [e["type"] for e in events]
    status = next(e for e in events if e["type"] == "status")
    assert status["text"].startswith("Counting") and kinds.index("status") < kinds.index("done")
    saved = (await db.execute(select(Message).where(Message.role == "assistant"))).scalars().one()
    assert "Counting" not in saved.content and saved.cards == []  # status lines are live only, never saved
