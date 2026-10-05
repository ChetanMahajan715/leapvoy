"""POST /chat/stream: Server-Sent Events: chat, text…, card…, done | error. Incognito chats are never stored."""

import json
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import current_user, get_sm
from app.chat import agent, store, tools
from app.db.models import User
from app.llm import models
from app.llm.router import LLMUnavailable

router = APIRouter()
log = structlog.get_logger()


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=20_000)
    cards: list[dict] = Field(default_factory=list, max_length=10)  # as streamed; their notes keep job ids


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    chat_id: int | None = None
    incognito: bool = False
    history: list[Turn] = Field(default_factory=list, max_length=40)  # incognito only: the app keeps the turns
    model: str | None = None  # model picker: None = Auto


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(body: ChatIn, user: User = Depends(current_user), sm: async_sessionmaker = Depends(get_sm)):
    user_id = user.id
    if body.model and body.model not in models.available():
        raise HTTPException(400, "That AI model isn't available.")
    async with sm() as s:
        if body.chat_id is not None and not body.incognito and await store.get_chat(s, user_id, body.chat_id) is None:
            raise HTTPException(404, "No such chat")

    async def events():
        async with sm() as s:
            chat_id, new = body.chat_id, False
            if body.incognito:
                history = agent.history_for_ai(body.history[-agent.HISTORY:])
            else:
                if chat_id is None:
                    chat_id, new = (await store.create_chat(s, user_id)).id, True
                history = agent.history_for_ai(await store.messages(s, user_id, chat_id, limit=agent.HISTORY))
                await store.add_message(s, user_id, chat_id, "user", body.message)
            yield sse({"type": "chat", "chat_id": chat_id, "incognito": body.incognito})

            ctx = tools.Context(now=datetime.now(UTC), incognito=body.incognito, last_user_message=body.message)
            text, cards = "", []
            try:
                async for event in agent.respond(s, user_id, history, body.message, ctx, model=body.model):
                    if event["type"] == "text":
                        text += event["text"]
                    elif event["type"] == "model":
                        event = {**event, "label": models.label(event["model"])}  # "answered by Ministral 14B"
                    elif event["type"] == "card":
                        cards.append(event["card"])  # status events are live only, never saved
                    yield sse(event)
            except LLMUnavailable:
                yield sse({"type": "error", "message": "The free AI is busy right now. Try again in a minute."})
                return
            except Exception:
                log.exception("chat.failed", user_id=str(user_id))
                yield sse({"type": "error", "message": "Something went wrong. Please try again."})
                return

            done = {"type": "done", "chat_id": chat_id}
            if not body.incognito:
                msg = await store.add_message(s, user_id, chat_id, "assistant", text, cards)
                done["message_id"] = msg.id
                if new:
                    done["title"] = (await store.update_chat(
                        s, user_id, chat_id, title=await agent.make_title(body.message))).title
            yield sse(done)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
