"""The chat assistant: stream text, run the tools the AI asks for, feed results back, repeat (max MAX_ROUNDS)."""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import tools
from app.db.models import Memory, Message
from app.llm import prompts
from app.llm.router import stream_chat, structured
from app.pipeline.report import IST

MAX_ROUNDS = 4
EM_DASH = chr(0x2014)


def no_em_dash(text: str) -> str:
    """The user never wants the em dash character in answers (works on streamed pieces too)."""
    return text.replace(EM_DASH, "-")
HISTORY = 20  # past messages given to the AI


class ChatTitle(BaseModel):
    title: str


async def make_title(first_message: str) -> str:
    """3–6 word title for the sidebar (small model); falls back to the first words."""
    try:
        out = await structured("small", [
            {"role": "system", "content": "Give a 3-6 word title for a chat that starts with this message. No quotes."},
            {"role": "user", "content": first_message[:500]},
        ], ChatTitle, max_retries=1)
        return out.title.strip().strip('"')[:80] or first_message[:40]
    except Exception:  # noqa: BLE001, a title is never worth failing the chat
        return " ".join(first_message.split()[:6])[:60] or "New chat"


def history_for_ai(msgs: list[Message]) -> list[dict]:
    """Past turns; assistant turns carry what their cards showed, so 'send the first one' still works."""
    out = []
    for m in msgs:
        notes = [c["note"] for c in m.cards if c.get("note")]
        content = m.content + (f"\n\n(Shown to the user: {' | '.join(notes)})" if notes else "")
        out.append({"role": m.role, "content": content})
    return out


async def system_prompt(s: AsyncSession, user_id: uuid.UUID, now: datetime, incognito: bool) -> str:
    memories = (await s.execute(select(Memory.text).where(Memory.user_id == user_id).order_by(Memory.id))).scalars().all()
    return prompts.load("chat").format(
        today=f"{now.astimezone(IST):%A %d %B %Y, %I:%M %p}",
        memories="\n".join(f"- {m}" for m in memories) or "- (nothing yet)",
        incognito="- This is an INCOGNITO chat: it is not saved and nothing goes to memory.\n" if incognito else "",
    )


# What the app shows while a tool runs (live only, never saved): long steps never look like an endless spinner
STATUS = {
    "list_jobs": "Looking up your jobs…",
    "list_posts": "Reading that day's jobs…",
    "search_posts": "Searching your posts…",
    "check_telegram": "Reading Telegram and checking new posts… this can take up to a minute",
    "analyze_pasted_job": "Reading the job post and checking your fit…",
    "write_email": "Writing the email…",
    "schedule_email": "Preparing it for your confirmation…",
    "list_scheduled": "Checking your scheduled emails…",
    "cancel_email": "Preparing it for your confirmation…",
    "reschedule_email": "Preparing it for your confirmation…",
    "stats": "Counting your numbers…",
    "remember": "Saving that…",
}


async def respond(
    s: AsyncSession, user_id: uuid.UUID, history: list[dict], text: str, ctx: tools.Context, model: str | None = None
) -> AsyncIterator[dict[str, Any]]:
    """Yields {"type": "text", "text"}, {"type": "card", "card"}, {"type": "model", "model"} (who answered) and
    {"type": "status", "text"} (what a tool is doing right now) events.
    model: the user's pick in the model picker (None = Auto); other models stay as backup."""
    messages = [
        {"role": "system", "content": await system_prompt(s, user_id, ctx.now, ctx.incognito)},
        *history,
        {"role": "user", "content": text},
    ]
    done: set[tuple[str, str]] = set()  # (tool, args) already run this turn: small models sometimes repeat a call
    for _ in range(MAX_ROUNDS):
        calls = []
        async for kind, value in stream_chat("small", messages, tools.TOOLS, prefer=model):
            if kind == "text":
                yield {"type": "text", "text": no_em_dash(value)}
            elif kind == "model":
                yield {"type": "model", "model": value}
            else:
                calls = value
        if not calls:
            return
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in calls
        ]})
        for c in calls:
            try:
                args = json.loads(c.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            args = args if isinstance(args, dict) else {}
            key = (c.name, json.dumps(args, sort_keys=True))
            if key in done:
                messages.append({"role": "tool", "tool_call_id": c.id,
                                 "content": "You already did this above. Don't repeat it. Answer the user now."})
                continue
            done.add(key)
            yield {"type": "status", "text": STATUS.get(c.name, "Working on it…")}
            result = await tools.run_tool(s, user_id, c.name, args, ctx)
            if result.card:
                yield {"type": "card", "card": result.card | {"note": result.text[:600]}}
            messages.append({"role": "tool", "tool_call_id": c.id, "content": result.text})
    yield {"type": "text", "text": "\n\n(I stopped after several steps. Tell me what to do next.)"}
