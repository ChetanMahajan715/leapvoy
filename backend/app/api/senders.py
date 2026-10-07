"""Email accounts (App Password over SMTP) and sending settings (test mode). The password never leaves the server."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.profile import get_profile
from app.api.deps import current_user, get_db
from app.api.ratelimit import limiter
from app.db.models import SenderAccount, Send, User
from app.mailer import outbox, senders

router = APIRouter()


async def _own(s: AsyncSession, user_id: uuid.UUID, sender_id: int) -> SenderAccount:
    acc = (await s.execute(select(SenderAccount).where(SenderAccount.id == sender_id, SenderAccount.user_id == user_id))
           ).scalar_one_or_none()
    if acc is None:
        raise HTTPException(404, "No such email account")
    return acc


async def _counts(s: AsyncSession, sender_id: int, status: tuple[str, ...], since: datetime | None = None) -> int:
    q = select(func.count()).select_from(Send).where(Send.sender_id == sender_id, Send.status.in_(status))
    if since is not None:
        q = q.where(Send.sent_at >= since)
    return await s.scalar(q)


async def sender_json(s: AsyncSession, acc: SenderAccount) -> dict:
    midnight = outbox._ist_day(datetime.now(UTC))  # India day, like the daily limit
    return {"id": acc.id, "email": acc.email, "provider": acc.provider, "is_default": acc.is_default,
            "daily_limit": acc.daily_limit, "sent_today": await _counts(s, acc.id, ("sent",), midnight),
            "scheduled": await _counts(s, acc.id, ("scheduled", "sending")),
            "app_password_help": senders.PROVIDERS[acc.provider].app_password_help}


async def _list(s: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    rows = (await s.execute(select(SenderAccount).where(SenderAccount.user_id == user_id)
                            .order_by(SenderAccount.created_at, SenderAccount.id))).scalars().all()
    return [await sender_json(s, a) for a in rows]


@router.get("/senders")
async def list_senders(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    return await _list(s, user.id)


class Connect(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=4, max_length=200)


@router.post("/senders")
@limiter.limit("5/minute")
async def connect(request: Request, body: Connect, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """Mails the address itself first; saved (encrypted) only when the login works. Same address = new password."""
    name = (await get_profile(s, user.id)).get("full_name") or "Leapvoy"
    try:
        acc = await senders.add_sender(s, user.id, body.email, body.password, name=name)
    except ValueError as e:  # unsupported domain
        raise HTTPException(400, str(e)) from None
    except senders.SenderLoginFailed as e:
        raise HTTPException(400, str(e)) from None
    except OSError:
        raise HTTPException(502, "Couldn't reach the mail server. Check the internet and try again.") from None
    return await sender_json(s, acc)


@router.post("/senders/{sender_id}/default")
async def make_default(sender_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    acc = await _own(s, user.id, sender_id)
    for other in (await s.execute(select(SenderAccount).where(SenderAccount.user_id == user.id))).scalars():
        other.is_default = other.id == acc.id
    await s.commit()
    return await sender_json(s, acc)


DEFAULT_LIMIT = 20  # new accounts start here (safe for a personal Gmail)
MAX_LIMIT = 500  # Gmail's own ceiling for a personal account; above it Gmail blocks sending for a day


class Limit(BaseModel):
    daily_limit: int = Field(ge=1, le=MAX_LIMIT)  # the user's choice (user, 3 Oct: no 20 cap)


@router.patch("/senders/{sender_id}")
async def set_limit(sender_id: int, body: Limit, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    acc = await _own(s, user.id, sender_id)
    acc.daily_limit = body.daily_limit
    await s.commit()
    return await sender_json(s, acc)


@router.post("/senders/{sender_id}/test")
@limiter.limit("5/minute")
async def test_mail(request: Request, sender_id: int, user: User = Depends(current_user),
                    s: AsyncSession = Depends(get_db)):
    """Re-checks the saved login by mailing the address itself."""
    acc = await _own(s, user.id, sender_id)
    name = (await get_profile(s, user.id)).get("full_name") or "Leapvoy"
    msg = senders.build_message(name, acc.email, acc.email, "Leapvoy test email",
                                "This address can still send emails through Leapvoy.")
    try:
        await senders.smtp_send(msg, acc.email, senders.password_of(acc))
    except senders.SenderLoginFailed as e:
        raise HTTPException(400, str(e)) from None
    except OSError:
        raise HTTPException(502, "Couldn't reach the mail server. Check the internet and try again.") from None
    return {"ok": True}


@router.delete("/senders/{sender_id}")
async def remove(sender_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    acc = await _own(s, user.id, sender_id)
    if await _counts(s, acc.id, ("scheduled", "sending")):
        raise HTTPException(409, "Emails are scheduled from this account. Cancel them or let them send first.")
    was_default = acc.is_default
    await s.delete(acc)
    await s.flush()
    if was_default:  # the oldest remaining account takes over
        nxt = (await s.execute(select(SenderAccount).where(SenderAccount.user_id == user.id)
                               .order_by(SenderAccount.created_at, SenderAccount.id))).scalars().first()
        if nxt:
            nxt.is_default = True
    await s.commit()
    return Response(status_code=204)


async def _sending(s: AsyncSession, user_id: uuid.UUID) -> dict:
    return {"test_mode": await outbox.is_test_mode(s, user_id),
            "rules": {"daily_limit_default": DEFAULT_LIMIT, "daily_limit_max": MAX_LIMIT, "gap_minutes": [outbox.GAP_MIN // 60, outbox.GAP_MAX // 60],
                      "hr_cooldown_days": outbox.COOLDOWN.days},
            "senders": len(await _list(s, user_id))}


@router.get("/sending")
async def read_sending(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    return await _sending(s, user.id)


class SendingIn(BaseModel):
    test_mode: bool
    confirm: bool = False  # required to turn test mode OFF (emails then go to HR)


@router.put("/sending")
async def save_sending(body: SendingIn, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    if not body.test_mode:
        if await senders.default_sender(s, user.id) is None:
            raise HTTPException(400, "Connect an email account first. Real emails need one to send from.")
        if not body.confirm:
            raise HTTPException(400, "Turning test mode off sends real emails to the addresses in the job posts. Please confirm it first.")
    await outbox.set_test_mode(s, user.id, body.test_mode)
    return await _sending(s, user.id)
