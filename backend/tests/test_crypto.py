import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

from app.core import crypto
from app.core.config import get_settings

KEY = os.urandom(32)


def test_round_trip():
    assert crypto.decrypt(crypto.encrypt(b"session", KEY, b"user-a"), KEY, b"user-a") == b"session"


def test_wrong_aad_fails():
    # a blob encrypted for user A can't be decrypted as user B's
    with pytest.raises(InvalidTag):
        crypto.decrypt(crypto.encrypt(b"session", KEY, b"user-a"), KEY, b"user-b")


def test_tampered_blob_fails():
    blob = bytearray(crypto.encrypt(b"session", KEY, b"u"))
    blob[-1] ^= 1
    with pytest.raises(InvalidTag):
        crypto.decrypt(bytes(blob), KEY, b"u")


def test_same_plaintext_encrypts_differently():
    assert crypto.encrypt(b"x", KEY, b"u") != crypto.encrypt(b"x", KEY, b"u")


def test_master_key_rejects_wrong_length(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/d")
    monkeypatch.setenv("MASTER_KEY", base64.b64encode(os.urandom(16)).decode())
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            crypto.master_key()
    finally:
        get_settings.cache_clear()
