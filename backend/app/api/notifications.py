"""Notifications: the inbox (web + phone), this phone's push token, and the user's notification choices."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import notify
from app.api.deps import current, current_user, get_db
from app.db.models import Device, Notification, User

router = APIRouter()


class TokenIn(BaseModel):
    token: str | None = Field(None, max_length=200)  # None = this phone turned notifications off


@router.post("/push-token")
async def push_token(body: TokenIn, me: tuple[User, Device] = Depends(current), s: AsyncSession = Depends(get_db)):
    if body.token and not body.token.startswith(("ExponentPushToken[", "ExpoPushToken[")):
        raise HTTPException(400, "Not an Expo push token.")
    device = await s.get(Device, me[1].id)
    await notify.set_token(s, device, body.token)
    return {"ok": True}


@router.get("/notifications")
async def inbox(limit: int = 50, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    mine = (Notification.user_id == user.id, Notification.hidden.is_(False))
    rows = (await s.execute(select(Notification).where(*mine)
                            .order_by(Notification.id.desc()).limit(min(max(limit, 1), 200)))).scalars().all()
    unread = await s.scalar(select(func.count()).select_from(Notification).where(*mine, Notification.read_at.is_(None)))
    return {"unread": unread, "items": [
        {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "data": n.data,
         "read": n.read_at is not None, "created_at": n.created_at.isoformat()} for n in rows]}


class ReadIn(BaseModel):
    ids: list[int] | None = None  # None = all


@router.post("/notifications/read")
async def mark_read(body: ReadIn, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    q = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if body.ids is not None:
        q = q.where(Notification.id.in_(body.ids))
    await s.execute(q.values(read_at=datetime.now(UTC)))
    await s.commit()
    return {"ok": True}


@router.post("/notifications/delete")
async def delete(body: ReadIn, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """ids=None: Clear all. Hidden, not removed, so a deleted job alert never comes back as new after a re-check."""
    q = update(Notification).where(Notification.user_id == user.id, Notification.hidden.is_(False))
    if body.ids is not None:
        q = q.where(Notification.id.in_(body.ids))
    await s.execute(q.values(hidden=True, read_at=func.coalesce(Notification.read_at, datetime.now(UTC)), push="none"))
    await s.commit()
    return {"ok": True}


KINDS = ("job", "summary", "reply", "send_failed", "limit", "new_device", "telegram_out", "ai_paused")


class PrefsIn(BaseModel):
    off: list[str] | None = None
    min_fit: str | None = None
    quiet_from: int | None = Field(None, ge=0, le=23)
    quiet_to: int | None = Field(None, ge=0, le=23)


@router.get("/notify-prefs")
async def get_prefs(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    return await notify.prefs(s, user.id)


@router.put("/notify-prefs")
async def put_prefs(body: PrefsIn, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    values = body.model_dump(exclude_none=True)
    if any(k not in KINDS or k in notify.ALWAYS for k in values.get("off", [])):
        raise HTTPException(400, "Unknown kind, or a security alert (those always come).")
    if "min_fit" in values and values["min_fit"] not in notify.FITS:
        raise HTTPException(400, "min_fit must be TOP PRIORITY, STRONG MATCH or APPLY.")
    return await notify.save_prefs(s, user.id, values)
