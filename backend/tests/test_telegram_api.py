"""Telegram login + channels API with a fake Telegram client: nothing here talks to real Telegram."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from telethon.errors import PhoneCodeExpiredError, PhoneCodeInvalidError, SessionPasswordNeededError

from app.api import telegram as tg_api
from app.db.models import Channel, Post, TelegramAccount, User
from app.telegram import reader, store
from tests.conftest import requires_db
from tests.test_auth_api import PW, api, bearer, secrets  # noqa: F401 (fixtures)

pytestmark = requires_db
DIALOGS = [(-1001, "SDE Premium Referrals 2.O", "sde_ref"), (-1002, "AI Jobs India", None)]


class FakeClient:
    """Enough of TelegramClient for the login flow. code '11111' is right; '22222' needs a 2-step password."""
    instances: list["FakeClient"] = []
    authorized_sessions: set[str] = set()

    def __init__(self, session_str: str = ""):
        self.session_str, self.calls = session_str or "half-done", []
        FakeClient.instances.append(self)
        self.session = SimpleNamespace(save=lambda: "logged-in" if self.signed else self.session_str)
        self.signed = False

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def is_user_authorized(self):
        return self.session_str in FakeClient.authorized_sessions

    async def send_code_request(self, phone):
        self.calls.append(("code", phone))
        return SimpleNamespace(phone_code_hash="hash-1")

    async def sign_in(self, phone=None, code=None, password=None, phone_code_hash=None):
        self.calls.append(("sign_in", phone, code, password, phone_code_hash))
        if password is not None:
            if password != "secret":
                from telethon.errors import PasswordHashInvalidError
                raise PasswordHashInvalidError(request=None)
        elif code == "00000":
            raise PhoneCodeExpiredError(request=None)
        elif code == "22222":
            raise SessionPasswordNeededError(request=None)
        elif code != "11111":
            raise PhoneCodeInvalidError(request=None)
        self.signed = True
        FakeClient.authorized_sessions.add("logged-in")

    async def get_me(self):
        return SimpleNamespace(first_name="Chetan", last_name=None, phone="919876543210")

    async def get_dialogs(self):
        return [SimpleNamespace(id=i, name=n, is_channel=True, is_group=False, entity=SimpleNamespace(username=u))
                for i, n, u in DIALOGS]

    async def log_out(self):
        self.calls.append(("log_out",))

    async def qr_login(self):
        return FakeQR(self)


class FakeQR:
    """Telethon's QRLogin: the test decides what the next wait() does via FakeQR.next (a list of outcomes)."""
    next: list[str] = []  # "expire" → TimeoutError, "scan" → logged in, "password" → 2-step password needed

    def __init__(self, client):
        self.client, self.n = client, 1
        self.url = "tg://login?token=t1"

    async def wait(self, timeout=None):
        import asyncio
        while not FakeQR.next:
            await asyncio.sleep(0.01)
        outcome = FakeQR.next.pop(0)
        if outcome == "expire":
            raise asyncio.TimeoutError
        if outcome == "password":
            raise SessionPasswordNeededError(request=None)
        self.client.signed = True
        FakeClient.authorized_sessions.add("logged-in")

    async def recreate(self):
        self.n += 1
        self.url = f"tg://login?token=t{self.n}"


@pytest.fixture
def fake_tg(monkeypatch):
    FakeClient.instances, FakeClient.authorized_sessions = [], set()
    monkeypatch.setattr(tg_api, "new_client", lambda session_str="": FakeClient(session_str))

    async def fake_connect(session_str):
        c = FakeClient(session_str)
        if not await c.is_user_authorized():
            raise reader.SessionRevoked
        return c

    monkeypatch.setattr(reader, "connect", fake_connect)
    tg_api._pending.clear()
    tg_api._qr.clear()
    FakeQR.next = []
    return FakeClient


async def user(api, email="a@x.com"):
    return bearer((await api.post("/auth/signup", json={"email": email, "password": PW, "device_name": "t"})).json())


async def test_login_with_code_then_channels(api, db, fake_tg):
    h = await user(api)
    assert (await api.get("/telegram", headers=h)).json()["connected"] is False
    assert (await api.post("/telegram/code", headers=h, json={"phone": "+91 98765 43210"})).json() == {"sent": True}
    r = await api.post("/telegram/verify", headers=h, json={"code": "11111"})
    assert r.status_code == 200 and r.json()["connected"] is True and r.json()["name"] == "Chetan"
    login = fake_tg.instances[-1].calls[-1]
    assert login == ("sign_in", "+919876543210", "11111", None, "hash-1")  # same half-done session + Telegram's hash
    s = (await api.get("/telegram", headers=h)).json()
    assert s["connected"] and s["phone"].startswith("+91") and "•" in s["phone"] and not s["revoked"]
    chans = (await api.get("/channels", headers=h)).json()
    assert [c["title"] for c in chans] == ["AI Jobs India", "SDE Premium Referrals 2.O"] and not chans[0]["enabled"]


async def test_two_step_password_is_used_once_and_never_stored(api, db, fake_tg):
    h = await user(api)
    await api.post("/telegram/code", headers=h, json={"phone": "+919876543210"})
    assert (await api.post("/telegram/verify", headers=h, json={"code": "22222"})).json() == {"needs_password": True}
    r = await api.post("/telegram/password", headers=h, json={"password": "wrong"})
    assert r.status_code == 400 and "password" in r.json()["detail"].lower()
    assert (await api.post("/telegram/password", headers=h, json={"password": "secret"})).json()["connected"]
    acc = (await db.execute(select(TelegramAccount))).scalar_one()
    assert b"secret" not in acc.session_enc


async def test_wrong_and_expired_codes_are_explained(api, db, fake_tg):
    h = await user(api)
    r = await api.post("/telegram/verify", headers=h, json={"code": "11111"})
    assert r.status_code == 400 and "Send a new code" in r.json()["detail"]  # no code was requested
    await api.post("/telegram/code", headers=h, json={"phone": "+919876543210"})
    r = await api.post("/telegram/verify", headers=h, json={"code": "12345"})
    assert r.status_code == 400 and "didn't match" in r.json()["detail"]
    r = await api.post("/telegram/verify", headers=h, json={"code": "00000"})
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    r = await api.post("/telegram/code", headers=h, json={"phone": "12"})
    assert r.status_code == 422


async def test_channels_on_off_refresh_backfill_and_logout(api, db, fake_tg, monkeypatch):
    h = await user(api)
    await api.post("/telegram/code", headers=h, json={"phone": "+919876543210"})
    await api.post("/telegram/verify", headers=h, json={"code": "11111"})
    sde = next(c for c in (await api.get("/channels", headers=h)).json() if c["title"].startswith("SDE"))
    assert (await api.patch(f"/channels/{sde['id']}", headers=h, json={"enabled": True})).json()["enabled"]
    assert (await api.get("/channels", headers=h)).json()[0]["title"].startswith("SDE")  # enabled first
    DIALOGS.append((-1003, "New Channel", None))
    try:
        assert len((await api.post("/channels/refresh", headers=h)).json()) == 3
    finally:
        DIALOGS.pop()
    started = {}

    async def fake_catch_up(client, sm, user_id, since=None, from_start=False, now=None):
        started.update(user_id=user_id, from_start=from_start, since=since)
        return 0

    monkeypatch.setattr(reader, "catch_up", fake_catch_up)
    r = await api.post("/telegram/backfill", headers=h, json={"days": 30})
    assert r.status_code == 200 and r.json()["started"] is True
    await tg_api.wait_for_backfills()
    assert started["from_start"] is True
    assert (await api.post("/telegram/logout", headers=h)).status_code == 200
    assert ("log_out",) in fake_tg.instances[-1].calls
    assert (await db.execute(select(TelegramAccount))).first() is None
    assert (await api.get("/telegram", headers=h)).json()["connected"] is False


async def test_revoked_session_is_reported(api, db, fake_tg):
    h = await user(api)
    uid = (await db.execute(select(User.id).where(User.email == "a@x.com"))).scalar_one()
    await store.save_session(db, uid, "+919876543210", "ended-by-telegram")
    s = (await api.get("/telegram", headers=h)).json()
    assert s["connected"] is True and s["revoked"] is True


async def test_other_users_cannot_see_or_change_my_channels(api, db, fake_tg):
    a = await user(api, "a@x.com")
    b = await user(api, "b@x.com")
    await api.post("/telegram/code", headers=a, json={"phone": "+919876543210"})
    await api.post("/telegram/verify", headers=a, json={"code": "11111"})
    cid = (await api.get("/channels", headers=a)).json()[0]["id"]
    assert (await api.get("/channels", headers=b)).json() == []
    assert (await api.patch(f"/channels/{cid}", headers=b, json={"enabled": True})).status_code == 404
    assert (await api.post("/telegram/verify", headers=b, json={"code": "11111"})).status_code == 400  # a's pending login


async def qr_state(api, h, want, tries=200):
    import asyncio
    for _ in range(tries):
        r = (await api.get("/telegram/qr", headers=h)).json()
        if r["state"] == want:
            return r
        await asyncio.sleep(0.01)
    raise AssertionError(f"never reached {want}: {r}")


async def test_qr_login_scan_with_the_phone_then_channels(api, db, fake_tg):
    h = await user(api)
    r = (await api.post("/telegram/qr", headers=h)).json()
    assert r["state"] == "waiting" and r["url"] == "tg://login?token=t1" and r["qr_png"].startswith("data:image/png")
    FakeQR.next.append("expire")  # Telegram's token runs out (~30 s): a fresh QR replaces it
    r = await qr_state(api, h, "waiting")
    for _ in range(200):
        if r["url"].endswith("t2"):
            break
        r = (await api.get("/telegram/qr", headers=h)).json()
    assert r["url"] == "tg://login?token=t2"
    other = await user(api, "b@x.com")
    assert (await api.get("/telegram/qr", headers=other)).json()["state"] == "none"  # your QR is yours only
    FakeQR.next.append("scan")
    await qr_state(api, h, "done")
    s = (await api.get("/telegram", headers=h)).json()
    assert s["connected"] and s["phone"].startswith("+91")  # the phone number comes from Telegram itself
    assert [c["title"] for c in (await api.get("/channels", headers=h)).json()] == ["AI Jobs India", "SDE Premium Referrals 2.O"]


async def test_qr_login_with_two_step_password(api, db, fake_tg):
    h = await user(api)
    await api.post("/telegram/qr", headers=h)
    FakeQR.next.append("password")
    await qr_state(api, h, "needs_password")
    assert (await api.post("/telegram/password", headers=h, json={"password": "secret"})).json()["connected"]
    acc = (await db.execute(select(TelegramAccount))).scalar_one()
    assert acc.phone == "+919876543210" and b"secret" not in acc.session_enc


async def test_a_new_qr_replaces_the_old_one(api, db, fake_tg):
    h = await user(api)
    await api.post("/telegram/qr", headers=h)
    first = tg_api._qr[next(iter(tg_api._qr))].task
    await api.post("/telegram/qr", headers=h)
    import asyncio
    await asyncio.sleep(0.05)
    assert first.cancelled() or first.done()
    assert (await api.get("/telegram/qr", headers=h)).json()["state"] == "waiting"
