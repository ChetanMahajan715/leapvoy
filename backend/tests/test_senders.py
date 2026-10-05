import base64
import os

import aiosmtplib
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import SenderAccount
from app.mailer import senders
from app.telegram import store
from tests.conftest import requires_db


@pytest.fixture
def smtp(monkeypatch):
    """Fake SMTP: records messages; raises for the password 'wrong'."""
    sent = []

    async def fake_send(message, **kw):
        if kw.get("password") == "wrong":
            raise aiosmtplib.SMTPAuthenticationError(535, "Username and Password not accepted")
        sent.append((message, kw))

    monkeypatch.setattr(senders, "_smtp_send", fake_send)
    return sent


@pytest.fixture
def master_key(monkeypatch):
    monkeypatch.setenv("MASTER_KEY", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://unused/x")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize(("email", "provider"), [
    ("me@gmail.com", "gmail"), ("me@outlook.com", "outlook"), ("me@hotmail.com", "outlook"),
    ("me@zoho.in", "zoho"), ("me@yahoo.com", "yahoo"),
])
def test_provider_from_address(email, provider):
    assert senders.provider_for(email) == provider


def test_unknown_provider_is_refused():
    with pytest.raises(ValueError, match="Gmail, Outlook, Zoho or Yahoo"):
        senders.provider_for("me@mycompany.dev")


@requires_db
async def test_add_sender_sends_a_test_mail_to_itself_and_saves_encrypted(db, smtp, master_key):
    uid = await store.get_or_create_user(db, "a@x.com")
    acc = await senders.add_sender(db, uid, "Me@Gmail.com", "abcd efgh ijkl mnop")
    [(msg, kw)] = smtp
    assert msg["To"] == "me@gmail.com" and kw["hostname"] == "smtp.gmail.com" and kw["port"] == 587
    assert kw["password"] == "abcdefghijklmnop"  # Google shows App Passwords with spaces
    assert acc.is_default and b"abcdefghijklmnop" not in acc.password_enc
    assert senders.password_of(acc) == "abcdefghijklmnop"


@requires_db
async def test_wrong_password_saves_nothing(db, smtp, master_key):
    uid = await store.get_or_create_user(db, "a@x.com")
    with pytest.raises(senders.SenderLoginFailed, match="App Password"):
        await senders.add_sender(db, uid, "me@gmail.com", "wrong")
    assert (await db.execute(select(SenderAccount))).first() is None


@requires_db
async def test_second_sender_is_not_default_and_senders_are_per_user(db, smtp, master_key):
    a = await store.get_or_create_user(db, "a@x.com")
    b = await store.get_or_create_user(db, "b@x.com")
    await senders.add_sender(db, a, "one@gmail.com", "pw1")
    second = await senders.add_sender(db, a, "two@gmail.com", "pw2")
    assert not second.is_default
    assert (await senders.default_sender(db, a)).email == "one@gmail.com"
    assert await senders.default_sender(db, b) is None
