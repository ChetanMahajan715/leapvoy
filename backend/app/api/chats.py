"""Chat list (sidebar Recents), messages, rename / pin / delete, search; memories; attached files → text."""

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import current_user, get_db
from app.chat import files, store
from app.db.models import Chat, Memory, User

MAX_FILE = 10 * 1024 * 1024
MAX_TEXT = 8000  # chars (~2k tokens): keeps the AI inside the free per-minute token limit

router = APIRouter()


class ChatPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=120)
    pinned: bool | None = None


def chat_json(c: Chat) -> dict:
    return {"id": c.id, "title": c.title, "pinned": c.pinned, "updated_at": c.updated_at}


@router.get("/chats")
async def list_chats(q: str | None = None, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    return [chat_json(c) for c in await store.list_chats(s, user.id, q)]


@router.post("/chats")
async def new_chat(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    return chat_json(await store.create_chat(s, user.id))


@router.get("/chats/{chat_id}/messages")
async def chat_messages(chat_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    if await store.get_chat(s, user.id, chat_id) is None:
        raise HTTPException(404, "No such chat")
    return [
        {"id": m.id, "role": m.role, "content": m.content, "cards": m.cards, "created_at": m.created_at}
        for m in await store.messages(s, user.id, chat_id)
    ]


@router.patch("/chats/{chat_id}")
async def patch_chat(chat_id: int, body: ChatPatch, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    chat = await store.update_chat(s, user.id, chat_id, **body.model_dump(exclude_none=True))
    if chat is None:
        raise HTTPException(404, "No such chat")
    return chat_json(chat)


@router.delete("/chats/{chat_id}", status_code=204)
async def remove_chat(chat_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    if not await store.delete_chat(s, user.id, chat_id):
        raise HTTPException(404, "No such chat")
    return Response(status_code=204)


@router.get("/memories")
async def list_memories(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    rows = (await s.execute(select(Memory).where(Memory.user_id == user.id).order_by(Memory.id))).scalars()
    return [{"id": m.id, "text": m.text, "created_at": m.created_at} for m in rows]


@router.delete("/memories/{memory_id}", status_code=204)
async def forget(memory_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    gone = await s.execute(delete(Memory).where(Memory.id == memory_id, Memory.user_id == user.id))
    await s.commit()
    if not gone.rowcount:
        raise HTTPException(404, "No such memory")
    return Response(status_code=204)


class Attachment(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    data: str = Field(max_length=MAX_FILE * 4 // 3 + 8)  # base64 (same JSON path on web and phones)


@router.post("/chat/extract")
async def file_text(body: Attachment, user: User = Depends(current_user)):
    """The app attaches a JD / post (PDF, Word, image, text); its text goes into the message box for the user to send."""
    try:
        data = base64.b64decode(body.data, validate=True)
    except binascii.Error:
        raise HTTPException(400, "The file didn't arrive correctly. Try again.") from None
    try:
        text = await run_in_threadpool(files.read_file, body.filename, data)
    except files.Unsupported as e:
        raise HTTPException(415, str(e)) from None
    return {"text": text[:MAX_TEXT], "truncated": len(text) > MAX_TEXT}
