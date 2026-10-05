"""Confirm / dismiss what the assistant proposed. Only this runs sends, cancels and moves."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PendingAction
from app.mailer import outbox
from app.mailer.drafts import JobNotFound
from app.pipeline.report import IST


class ActionError(ValueError):
    pass


async def _pending(s: AsyncSession, user_id: uuid.UUID, action_id: int) -> PendingAction:
    action = (await s.execute(
        select(PendingAction).where(PendingAction.id == action_id, PendingAction.user_id == user_id).with_for_update()
    )).scalar_one_or_none()  # row lock: a double tap can't run it twice
    if action is None:
        raise ActionError("No such action.")
    if action.status != "pending":
        raise ActionError(f"This was already {action.status}.")
    return action


async def confirm(s: AsyncSession, user_id: uuid.UUID, action_id: int, now: datetime | None = None) -> PendingAction:
    now = now or datetime.now(UTC)
    action = await _pending(s, user_id, action_id)
    p = action.payload
    try:
        if action.kind == "schedule":
            send = await outbox.approve(s, user_id, p["job_id"], datetime.fromisoformat(p["when"]), to=p["to"], now=now)
            result = f"Scheduled for {send.send_at.astimezone(IST):%a %d %b, %I:%M %p} IST."
        elif action.kind == "cancel":
            await outbox.cancel(s, user_id, p["send_id"])
            result = "Cancelled."
        elif action.kind == "reschedule":
            send = await outbox.reschedule(s, user_id, p["send_id"], datetime.fromisoformat(p["when"]), now=now)
            result = f"Moved to {send.send_at.astimezone(IST):%a %d %b, %I:%M %p} IST."
        else:
            raise ActionError(f"Unknown action {action.kind}")
        action.status, action.result = "done", result
    except (outbox.NotAllowed, JobNotFound) as e:
        action.status, action.result = "failed", str(e)
    await s.commit()
    return action


async def dismiss(s: AsyncSession, user_id: uuid.UUID, action_id: int) -> PendingAction:
    action = await _pending(s, user_id, action_id)
    action.status, action.result = "dismissed", "Not sent."
    await s.commit()
    return action
