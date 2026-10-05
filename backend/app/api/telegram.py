"""Telegram from the app: log in (phone → code, or scan a QR code with the Telegram app; then an optional 2-step
password), log out, pick channels, read older posts.
Leapvoy only reads Telegram. The 2-step password is used once and never stored; the session is saved encrypted."""

import asyncio
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from app.accounts.auth import qr_png
from app.api.deps import current_user, get_db
from app.api.ratelimit import limiter
from app.core.config import get_settings
from app.db.models import Channel, Post, TelegramAccount, User
from app.telegram import reader, store

log = structlog.get_logger()
router = APIRouter()
PENDING_FOR = 600  # seconds a half-finished login is kept


@dataclass
class Pending:
    session: str  # Telethon session right after send_code_request (same auth key must finish the login)
    phone: str
    code_hash: str
    expires: float
    needs_password: bool = False


@dataclass
class QrLogin:
    """A QR login waiting for the user's Telegram app to scan it (one live connection, at most PENDING_FOR)."""
    client: TelegramClient
    url: str
    state: str = "waiting"  # waiting | needs_password | done | expired | error
    error: str | None = None
    task: asyncio.Task | None = None


# ponytail: in memory (one API process); a restart just means "send a new code" / "show a new QR"
_pending: dict[uuid.UUID, Pending] = {}
_qr: dict[uuid.UUID, QrLogin] = {}
_backfills: set[asyncio.Task] = set()


def configured() -> bool:
    s = get_settings()
    return bool(s.telegram_api_id and s.telegram_api_hash)


def new_client(session_str: str = "") -> TelegramClient:
    if not configured():
        raise HTTPException(503, "Telegram isn't set up on the server yet (TELEGRAM_API_ID / TELEGRAM_API_HASH).")
    s = get_settings()
    return TelegramClient(StringSession(session_str), s.telegram_api_id, s.telegram_api_hash)


def _mask(phone: str) -> str:
    return phone[:5] + "•" * max(len(phone) - 8, 0) + phone[-3:] if len(phone) > 8 else phone


async def _status(s: AsyncSession, user_id: uuid.UUID) -> dict:
    out = {"configured": configured(), "connected": False, "revoked": False, "name": None, "phone": None}
    acc = await s.get(TelegramAccount, user_id)
    if acc is None:
        return out
    out |= {"connected": True, "phone": _mask(acc.phone)}
    client = new_client(await store.load_session(s, user_id))
    try:
        await client.connect()
        if not await client.is_user_authorized():
            out["revoked"] = True
        else:
            me = await client.get_me()
            out["name"] = " ".join(filter(None, [me.first_name, me.last_name])) or None
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - offline / Telegram slow: still connected as far as we know
        log.warning("telegram.status_check_failed", user_id=str(user_id))
    finally:
        await client.disconnect()
    return out


@router.get("/telegram")
async def status(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    return await _status(s, user.id)


class PhoneIn(BaseModel):
    phone: str = Field(max_length=25)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v)
        if not 8 <= len(digits) <= 15:
            raise ValueError("Enter your phone number with the country code, like +91 98765 43210.")
        return "+" + digits


def _flood(e: FloodWaitError) -> HTTPException:
    return HTTPException(429, f"Telegram asks to wait {max(1, e.seconds // 60)} minute(s) before trying again.")


@router.post("/telegram/code")
@limiter.limit("3/minute")
async def send_code(request: Request, body: PhoneIn, user: User = Depends(current_user)):
    """Telegram sends a login code to the user's Telegram app (not SMS)."""
    client = new_client()
    try:
        await client.connect()
        sent = await client.send_code_request(body.phone)
        _pending[user.id] = Pending(client.session.save(), body.phone, sent.phone_code_hash, time.time() + PENDING_FOR)
    except PhoneNumberInvalidError:
        raise HTTPException(400, "Telegram doesn't know that number. Check it, with the country code.") from None
    except FloodWaitError as e:
        raise _flood(e) from None
    finally:
        await client.disconnect()
    return {"sent": True}


def _pending_for(user_id: uuid.UUID) -> Pending:
    p = _pending.get(user_id)
    if p is None or p.expires < time.time():
        _pending.pop(user_id, None)
        raise HTTPException(400, "No login in progress. Send a new code first.")
    return p


async def _finish(s: AsyncSession, user_id: uuid.UUID, client, phone: str) -> dict:
    """Logged in: save the session (encrypted) and load the channel list. A QR login has no typed phone: Telegram's own."""
    me = await client.get_me()
    phone = phone or ("+" + me.phone if me.phone else "")
    await store.save_session(s, user_id, phone, client.session.save())
    _pending.pop(user_id, None)
    dialogs = [d for d in await client.get_dialogs() if d.is_channel or d.is_group]
    await store.upsert_channels(s, user_id, [(d.id, d.name or "", getattr(d.entity, "username", None)) for d in dialogs])
    return {**await _status_quick(s, user_id), "name": " ".join(filter(None, [me.first_name, me.last_name])) or None}


async def _status_quick(s: AsyncSession, user_id: uuid.UUID) -> dict:
    acc = await s.get(TelegramAccount, user_id)
    return {"configured": True, "connected": acc is not None, "revoked": False, "name": None,
            "phone": _mask(acc.phone) if acc else None}


class CodeIn(BaseModel):
    code: str = Field(min_length=3, max_length=12)


@router.post("/telegram/verify")
@limiter.limit("5/minute")
async def verify(request: Request, body: CodeIn, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    p = _pending_for(user.id)
    client = new_client(p.session)
    try:
        await client.connect()
        try:
            await client.sign_in(p.phone, re.sub(r"\D", "", body.code), phone_code_hash=p.code_hash)
        except SessionPasswordNeededError:
            p.needs_password, p.session = True, client.session.save()
            return {"needs_password": True}
        except PhoneCodeInvalidError:
            raise HTTPException(400, "That code didn't match. Check the code in your Telegram app.") from None
        except PhoneCodeExpiredError:
            _pending.pop(user.id, None)
            raise HTTPException(400, "That code expired. Send a new code.") from None
        except FloodWaitError as e:
            raise _flood(e) from None
        return await _finish(s, user.id, client, p.phone)
    finally:
        await client.disconnect()


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


@router.post("/telegram/password")
@limiter.limit("5/minute")
async def two_step(request: Request, body: PasswordIn, user: User = Depends(current_user),
                   s: AsyncSession = Depends(get_db)):
    p = _pending_for(user.id)
    if not p.needs_password:
        raise HTTPException(400, "Enter the code from Telegram first.")
    client = new_client(p.session)
    try:
        await client.connect()
        try:
            await client.sign_in(password=body.password)  # used once, never stored
        except PasswordHashInvalidError:
            raise HTTPException(400, "That 2-step password is wrong. It's the one you set in Telegram's privacy settings.") from None
        except FloodWaitError as e:
            raise _flood(e) from None
        return await _finish(s, user.id, client, p.phone)
    finally:
        await client.disconnect()


async def _qr_wait(sm: async_sessionmaker, user_id: uuid.UUID, q: QrLogin, login) -> None:
    """Waits for the scan; Telegram's QR token lasts ~30 s, so a fresh one replaces it until PENDING_FOR runs out."""
    deadline = time.time() + PENDING_FOR
    try:
        while True:
            try:
                await login.wait()
                break
            except asyncio.TimeoutError:
                if time.time() > deadline:
                    q.state = "expired"
                    return
                await login.recreate()
                q.url = login.url
        async with sm() as s:
            await _finish(s, user_id, q.client, "")
        q.state = "done"
    except SessionPasswordNeededError:  # same as the code login: the password step finishes it
        _pending[user_id] = Pending(q.client.session.save(), "", "", time.time() + PENDING_FOR, needs_password=True)
        q.state = "needs_password"
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - Telegram refused / connection lost: say so, the user can start again
        log.exception("telegram.qr_login_failed", user_id=str(user_id))
        q.state, q.error = "error", "The QR login stopped. Show a new QR code, or log in with your phone number."
    finally:
        await q.client.disconnect()


def _qr_json(q: QrLogin | None) -> dict:
    if q is None:
        return {"state": "none"}
    out = {"state": q.state, "error": q.error}
    if q.state == "waiting":
        out |= {"url": q.url, "qr_png": qr_png(q.url)}
    return out


@router.post("/telegram/qr")
@limiter.limit("5/minute")
async def qr_start(request: Request, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """Log in by scanning a QR code with the Telegram app (Settings → Devices → Link Desktop Device): no code typing."""
    old = _qr.pop(user.id, None)
    if old and old.task:
        old.task.cancel()
    client = new_client()
    try:
        await client.connect()
        login = await client.qr_login()
    except FloodWaitError as e:
        await client.disconnect()
        raise _flood(e) from None
    q = _qr[user.id] = QrLogin(client, login.url)
    q.task = asyncio.create_task(_qr_wait(async_sessionmaker(s.bind, expire_on_commit=False), user.id, q, login))
    return _qr_json(q)


@router.get("/telegram/qr")
async def qr_status(user: User = Depends(current_user)):
    """The app asks every 2 s: still waiting (with the current QR), needs the 2-step password, done, or expired."""
    return _qr_json(_qr.get(user.id))


@router.post("/telegram/logout")
async def logout(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """Ends the session on Telegram's side too, then deletes it here."""
    session_str = await store.load_session(s, user.id)
    if session_str is not None:
        client = new_client(session_str)
        try:
            await client.connect()
            if await client.is_user_authorized():
                await client.log_out()
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 - offline: still forget it here
            log.warning("telegram.logout_remote_failed", user_id=str(user.id))
        finally:
            await client.disconnect()
        await store.delete_session(s, user.id)
    return {"connected": False}


async def channels_json(s: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    stats = (select(Post.channel_id, func.count().label("n"), func.max(Post.posted_at).label("last"))
             .where(Post.user_id == user_id).group_by(Post.channel_id).subquery())
    rows = (await s.execute(
        select(Channel, stats.c.n, stats.c.last).outerjoin(stats, stats.c.channel_id == Channel.id)
        .where(Channel.user_id == user_id, Channel.tg_chat_id != 0)  # 0 = "Pasted in chat", not a Telegram channel
        .order_by(Channel.enabled.desc(), func.lower(Channel.title))
    )).all()
    return [{"id": c.id, "title": c.title, "username": c.username, "enabled": c.enabled, "posts": n or 0,
             "last_post_at": last} for c, n, last in rows]


@router.get("/channels")
async def list_channels(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    return await channels_json(s, user.id)


class Toggle(BaseModel):
    enabled: bool


@router.patch("/channels/{channel_id}")
async def toggle(channel_id: int, body: Toggle, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    ch = (await s.execute(select(Channel).where(Channel.id == channel_id, Channel.user_id == user.id,
                                                Channel.tg_chat_id != 0))).scalar_one_or_none()
    if ch is None:
        raise HTTPException(404, "No such channel")
    ch.enabled = body.enabled
    await s.commit()
    return {"id": ch.id, "title": ch.title, "enabled": ch.enabled}


async def _connected_client(s: AsyncSession, user_id: uuid.UUID):
    session_str = await store.load_session(s, user_id)
    if session_str is None:
        raise HTTPException(400, "Connect Telegram first.")
    try:
        return await reader.connect(session_str)
    except reader.SessionRevoked:
        raise HTTPException(409, "Telegram signed Leapvoy out. Log in again.") from None


@router.post("/channels/refresh")
async def refresh(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """Reload joined channels (after joining new ones in Telegram)."""
    client = await _connected_client(s, user.id)
    try:
        dialogs = [d for d in await client.get_dialogs() if d.is_channel or d.is_group]
    finally:
        await client.disconnect()
    await store.upsert_channels(s, user.id, [(d.id, d.name or "", getattr(d.entity, "username", None)) for d in dialogs])
    return await channels_json(s, user.id)


class BackfillIn(BaseModel):
    days: int = Field(ge=1, le=90)


async def _backfill(sm: async_sessionmaker, user_id: uuid.UUID, client, days: int) -> None:
    try:
        n = await reader.catch_up(client, sm, user_id, since=datetime.now(UTC) - timedelta(days=days), from_start=True)
        log.info("telegram.backfill_done", user_id=str(user_id), days=days, saved=n)
    except Exception:  # noqa: BLE001
        log.exception("telegram.backfill_failed", user_id=str(user_id))
    finally:
        await client.disconnect()


@router.post("/telegram/backfill")
async def backfill(body: BackfillIn, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """Read older posts of the channels that are on, in the background; they show up in Jobs → All posts."""
    client = await _connected_client(s, user.id)
    task = asyncio.create_task(_backfill(async_sessionmaker(s.bind, expire_on_commit=False), user.id, client, body.days))
    _backfills.add(task)
    task.add_done_callback(_backfills.discard)
    return {"started": True, "days": body.days}


async def wait_for_backfills() -> None:
    """Tests (and shutdown) wait for running backfills."""
    if _backfills:
        await asyncio.gather(*_backfills)
