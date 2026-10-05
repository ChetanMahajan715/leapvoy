"""Sign up / sign in (email + password), optional 2FA (Google Authenticator), refresh, logout, devices, /me.

2FA is OFF by default (user's choice, 30 Sep 2026). Turned on in Settings → 2-step sign-in; then sign-in needs the code.
"""

import uuid
from typing import Literal
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import notify
from app.accounts import auth, deletion, recovery
from app.api.deps import current, current_user, get_db
from app.api.ratelimit import limiter
from app.core.config import get_settings
from app.db.models import Device, User
from app.mailer import outbox

router = APIRouter()
LIMIT = "5/minute"
TOTP_REQUIRED = "totp_required"  # the app then shows the 6-digit code field


class SignUp(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    device_name: str = Field(min_length=1, max_length=80)


class SignIn(SignUp):
    password: str = Field(min_length=1, max_length=200)
    code: str | None = Field(None, min_length=6, max_length=9)  # 6 digits or a backup code "k3m9-x7qa"


class Code(BaseModel):
    code: str = Field(min_length=6, max_length=9)


class Disable2FA(Code):
    password: str = Field(min_length=1, max_length=200)


class ChangePassword(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)
    code: str | None = Field(None, min_length=6, max_length=9)  # needed when 2-step sign-in is on
    sign_out_others: bool = True


class DeleteAccount(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    code: str | None = Field(None, min_length=6, max_length=9)
    confirm: Literal["DELETE"]  # typed by the user


class RefreshBody(BaseModel):
    refresh_token: str


async def _user(s: AsyncSession, email: str) -> User | None:
    return (await s.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()


@router.post("/auth/signup")
@limiter.limit(LIMIT)
async def signup(request: Request, body: SignUp, s: AsyncSession = Depends(get_db)):
    """Create the account (or claim one made by a CLI) and sign this device in."""
    email = body.email.lower()
    mode = get_settings().signup_mode
    owner = await s.scalar(select(func.count()).select_from(User).where(User.password_hash != "!"))
    if mode == "closed" or (mode == "first" and owner):
        raise HTTPException(403, "Sign-ups are closed on this server. Sign in with your existing account.")
    user = await _user(s, email)
    if user is not None and user.password_hash != "!":
        raise HTTPException(409, "This email already has an account. Sign in instead.")
    if user is None:
        user = User(id=uuid.uuid4(), email=email, password_hash="!")
        s.add(user)
    user.password_hash, user.totp_enabled = auth.hash_password(body.password), False
    await s.flush()
    return await auth.new_device(s, user, body.device_name)


@router.post("/auth/login")
@limiter.limit(LIMIT)
async def login(request: Request, body: SignIn, s: AsyncSession = Depends(get_db)):
    user = await _user(s, body.email)
    if not auth.password_ok(user, body.password):
        raise HTTPException(401, "Wrong email or password.")
    if user.totp_enabled:
        if not body.code:
            raise HTTPException(401, TOTP_REQUIRED)
        if not recovery.second_factor_ok(user, body.code):  # authenticator code or a backup code
            raise HTTPException(401, "Wrong code from the authenticator app.")
    if await s.scalar(select(func.count()).select_from(Device).where(Device.user_id == user.id, Device.revoked_at.is_(None))):
        await notify.add(s, user.id, "new_device", f"New sign-in on {body.device_name[:60] or 'a device'}",
                         "Not you? Sign that device out in Settings → Logged-in devices, then change your password.",
                         {"screen": "settings"})
    return await auth.new_device(s, user, body.device_name)  # commits the alert too


class ForgotBody(BaseModel):
    email: EmailStr


class ResetBody(ForgotBody):
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=10, max_length=200)


@router.post("/auth/password/forgot")
@limiter.limit("3/minute")
async def forgot_password(request: Request, body: ForgotBody, s: AsyncSession = Depends(get_db)):
    """Emails a 6-digit code if the account exists, the answer is the same either way."""
    try:
        await recovery.start_reset(s, body.email)
    except recovery.ResetNotConfigured:
        raise HTTPException(503, "Password reset by email is not set up on this server yet.") from None
    return {"message": "If that email has an account, a code is on its way (check spam too)."}


@router.post("/auth/password/reset")
@limiter.limit("10/minute")  # the real guard: 5 wrong tries lock the code
async def reset_password(request: Request, body: ResetBody, s: AsyncSession = Depends(get_db)):
    if not await recovery.finish_reset(s, body.email, body.code, body.new_password):
        raise HTTPException(400, "That code is wrong or expired. Ask for a new one.")
    return {"message": "Password changed. Sign in with your new password."}


def _check_identity(user: User, password: str, code: str | None) -> None:
    """Password, and the authenticator / backup code when 2-step sign-in is on."""
    if not auth.password_ok(user, password):
        raise HTTPException(401, "Your current password is wrong.")
    if user.totp_enabled and not (code and recovery.second_factor_ok(user, code)):
        raise HTTPException(401, "Enter the 6-digit code from your authenticator app (or a backup code).")


@router.post("/auth/password/change")
@limiter.limit(LIMIT)
async def change_password(request: Request, body: ChangePassword, me=Depends(current), s: AsyncSession = Depends(get_db)):
    user, this = me
    _check_identity(user, body.current_password, body.code)
    if body.new_password == body.current_password:
        raise HTTPException(400, "Choose a password different from the current one.")
    user.password_hash = auth.hash_password(body.new_password)
    if body.sign_out_others:  # whoever knew the old password is signed out; this device stays in
        await s.execute(update(Device).where(Device.user_id == user.id, Device.id != this.id,
                                             Device.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
    await s.commit()
    return {"message": "Password changed."}


@router.post("/auth/account/delete")
@limiter.limit(LIMIT)
async def delete_account(request: Request, body: DeleteAccount, user: User = Depends(current_user),
                         s: AsyncSession = Depends(get_db)):
    """Everything stops now; the account and all its data are deleted after 7 days unless the user keeps it."""
    _check_identity(user, body.password, body.code)
    when = await deletion.request_deletion(s, user, datetime.now(UTC))
    return {"delete_after": when}


@router.post("/auth/account/restore")
async def restore_account(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """'Keep my account' (signed in during the 7 days)."""
    await deletion.restore(s, user)
    return {"delete_after": None}


@router.post("/auth/2fa/setup")
async def setup_2fa(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """New key + QR code. 2FA stays off until the first code is confirmed (enable)."""
    if user.totp_enabled:
        raise HTTPException(409, "2-step sign-in is already on.")
    secret = auth.new_totp_secret(user)
    await s.commit()
    uri = auth.otpauth_uri(user.email, secret)
    return {"totp_secret": secret, "otpauth_uri": uri, "qr_png": auth.qr_png(uri)}


@router.post("/auth/2fa/enable")
@limiter.limit(LIMIT)
async def enable_2fa(request: Request, body: Code, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    if not auth.code_ok(user, body.code):
        raise HTTPException(400, "That code didn't match. Check the phone's time and try the newest code.")
    user.totp_enabled = True
    codes = recovery.new_backup_codes(user)  # shown once; for when the phone is lost
    await s.commit()
    return {"totp_enabled": True, "backup_codes": codes}


@router.post("/auth/2fa/disable")
@limiter.limit(LIMIT)
async def disable_2fa(
    request: Request, body: Disable2FA, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)
):
    if not auth.password_ok(user, body.password) or not recovery.second_factor_ok(user, body.code):
        raise HTTPException(401, "Wrong password or code.")
    user.totp_enabled, user.totp_secret_enc, user.backup_codes = False, None, []
    await s.commit()
    return {"totp_enabled": False}


@router.post("/auth/refresh")
@limiter.limit("30/minute")
async def refresh(request: Request, body: RefreshBody, s: AsyncSession = Depends(get_db)):
    try:
        return await auth.refresh(s, body.refresh_token)
    except auth.AuthError as e:
        raise HTTPException(401, str(e)) from e


@router.post("/auth/logout", status_code=204)
async def logout(me=Depends(current), s: AsyncSession = Depends(get_db)):
    device = await s.get(Device, me[1].id)
    device.revoked_at = datetime.now(UTC)
    await s.commit()
    return Response(status_code=204)


@router.get("/auth/devices")
async def devices(me=Depends(current), s: AsyncSession = Depends(get_db)):
    user, this = me
    rows = (await s.execute(
        select(Device).where(Device.user_id == user.id, Device.revoked_at.is_(None)).order_by(Device.created_at)
    )).scalars()
    return [{"id": d.id, "name": d.name, "created_at": d.created_at, "last_seen_at": d.last_seen_at,
             "current": d.id == this.id} for d in rows]


@router.delete("/auth/devices/{device_id}", status_code=204)
async def remove_device(device_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    device = (await s.execute(select(Device).where(
        Device.id == device_id, Device.user_id == user.id, Device.revoked_at.is_(None)
    ))).scalar_one_or_none()
    if device is None:
        raise HTTPException(404, "No such device")
    device.revoked_at = datetime.now(UTC)
    await s.commit()
    return Response(status_code=204)


@router.get("/me")
async def me(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    return {"id": str(user.id), "email": user.email, "totp_enabled": user.totp_enabled, "delete_after": user.delete_after,
            "test_mode": await outbox.is_test_mode(s, user.id)}  # the app says where a send really goes
