"""Passwords (argon2), TOTP 2FA (Google Authenticator), per-device tokens.

access token: short JWT (15 min) naming the user + device · refresh token: random, stored only as a hash on the
device row, rotated on every use · logout / remote logout revokes the device → both tokens die at once.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
import segno
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt, encrypt, master_key
from app.db.models import Device, User

ACCESS_TTL = timedelta(minutes=15)
ISSUER = "Leapvoy"
_ph = PasswordHasher()
_DUMMY = _ph.hash("timing-equaliser")  # unknown emails take as long as wrong passwords


class AuthError(Exception):
    """401: wrong email/password/code, or a dead token."""


def hash_password(password: str) -> str:
    return _ph.hash(password)


def password_ok(user: User | None, password: str) -> bool:
    real = user is not None and user.password_hash != "!"
    try:
        _ph.verify(user.password_hash if real else _DUMMY, password)
    except VerificationError:
        return False
    return real


def new_totp_secret(user: User) -> str:
    secret = pyotp.random_base32()
    user.totp_secret_enc = encrypt(secret.encode(), master_key(), user.id.bytes)
    return secret


def otpauth_uri(email: str, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def qr_png(uri: str) -> str:
    """QR code (PNG data URI) of the otpauth link: scan it with Google Authenticator instead of typing the key."""
    return segno.make(uri, error="m").png_data_uri(scale=6, border=2, dark="#0C0F1A", light="#FFFFFF")


def code_ok(user: User, code: str) -> bool:
    if not user.totp_secret_enc:
        return False
    secret = decrypt(user.totp_secret_enc, master_key(), user.id.bytes).decode()
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)  # ±30 s for phone clock drift


def _jwt_secret() -> str:
    secret = get_settings().jwt_secret
    if not secret:
        raise RuntimeError("JWT_SECRET is not set in .env")
    return secret


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _access(user_id: uuid.UUID, device_id: int) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "did": device_id, "iat": now, "exp": now + ACCESS_TTL, "typ": "access"}
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


async def new_device(s: AsyncSession, user: User, name: str) -> dict:
    refresh = secrets.token_urlsafe(32)
    device = Device(user_id=user.id, name=name[:80] or "Device", refresh_hash=_hash(refresh))
    s.add(device)
    await s.commit()
    return {"access_token": _access(user.id, device.id), "refresh_token": refresh, "device_id": device.id}


async def refresh(s: AsyncSession, token: str) -> dict:
    device = (await s.execute(
        select(Device).where(Device.refresh_hash == _hash(token), Device.revoked_at.is_(None))
    )).scalar_one_or_none()
    if device is None:
        raise AuthError("Session ended. Please sign in again.")
    new = secrets.token_urlsafe(32)
    device.refresh_hash, device.last_seen_at = _hash(new), datetime.now(UTC)
    await s.commit()
    return {"access_token": _access(device.user_id, device.id), "refresh_token": new, "device_id": device.id}


async def user_from_access(s: AsyncSession, token: str) -> tuple[User, Device]:
    try:
        claims = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise AuthError("Invalid or expired token") from e
    if claims.get("typ") != "access":
        raise AuthError("Invalid token")
    device = await s.get(Device, claims["did"])
    if device is None or device.revoked_at is not None or str(device.user_id) != claims["sub"]:
        raise AuthError("This device was logged out")
    return await s.get(User, device.user_id), device
