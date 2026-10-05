"""AES-GCM encryption for secrets at rest (Telegram sessions, App Passwords).

Blob = 12-byte random nonce + ciphertext/tag. `aad` binds a blob to its owner
(e.g. user_id), so a blob copied to another user's row won't decrypt.
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

# ponytail: one master key for everything; move to envelope encryption / OCI Vault if keys need rotating


def encrypt(plaintext: bytes, key: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def decrypt(blob: bytes, key: bytes, aad: bytes) -> bytes:
    return AESGCM(key).decrypt(blob[:12], blob[12:], aad)


def master_key() -> bytes:
    raw = get_settings().master_key
    if not raw:
        raise RuntimeError("MASTER_KEY is not set in .env (run: python -m app.telegram.cli keygen)")
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise RuntimeError("MASTER_KEY must be 32 bytes, base64-encoded")
    return key
