import base64
import os

import httpx
import pyotp
import pytest

from app.api.deps import get_db
from app.api.ratelimit import limiter
from app.core.config import get_settings
from app.main import app
from app.telegram import store
from tests.conftest import requires_db

pytestmark = requires_db
PW = "correct horse battery"


@pytest.fixture(autouse=True)
def secrets(monkeypatch):
    monkeypatch.setenv("MASTER_KEY", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("JWT_SECRET", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://unused/x")
    get_settings.cache_clear()
    limiter.reset()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def api(sm):
    async def test_db():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_db] = test_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def bearer(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def signup(api, email="me@x.com", device="Pixel 7"):
    r = await api.post("/auth/signup", json={"email": email, "password": PW, "device_name": device})
    assert r.status_code == 200, r.text
    return r.json()


async def login(api, email="me@x.com", password=PW, code=None, device="Laptop"):
    body = {"email": email, "password": password, "device_name": device}
    if code is not None:
        body["code"] = code
    return await api.post("/auth/login", json=body)


async def turn_on_2fa(api, tokens):
    setup = (await api.post("/auth/2fa/setup", headers=bearer(tokens))).json()
    r = await api.post("/auth/2fa/enable", headers=bearer(tokens), json={"code": pyotp.TOTP(setup["totp_secret"]).now()})
    assert r.status_code == 200, r.text
    return setup["totp_secret"]


# --- sign up: email + password, 2FA optional ----------------------------------------

async def test_signup_signs_you_in_without_2fa(api):
    tokens = await signup(api, "Me@X.com")
    me = (await api.get("/me", headers=bearer(tokens))).json()
    assert me == {"id": me["id"], "email": "me@x.com", "totp_enabled": False, "delete_after": None, "test_mode": True}  # test mode on by default


async def test_short_password_is_refused(api):
    r = await api.post("/auth/signup", json={"email": "a@x.com", "password": "short", "device_name": "x"})
    assert r.status_code == 422


async def test_cannot_sign_up_twice(api):
    await signup(api)
    r = await api.post("/auth/signup", json={"email": "me@x.com", "password": PW, "device_name": "x"})
    assert r.status_code == 409


async def test_account_created_by_the_cli_can_be_claimed_once(api, sm):
    async with sm() as s:
        await store.get_or_create_user(s, "cli@x.com")  # password "!" (unusable)
    await signup(api, "cli@x.com")
    r = await api.post("/auth/signup", json={"email": "cli@x.com", "password": PW, "device_name": "x"})
    assert r.status_code == 409


# --- sign in ------------------------------------------------------------------------------

async def test_without_2fa_password_is_enough(api):
    await signup(api)
    assert (await login(api)).status_code == 200
    assert (await login(api, password="wrong password!!")).status_code == 401


async def test_too_many_login_attempts_are_blocked(api):
    await signup(api)
    codes = [(await login(api, password="wrong password!!")).status_code for _ in range(6)]
    assert codes[-1] == 429


# --- optional 2FA -----------------------------------------------------------------------

async def test_2fa_setup_gives_qr_and_key(api):
    tokens = await signup(api)
    setup = (await api.post("/auth/2fa/setup", headers=bearer(tokens))).json()
    assert setup["qr_png"].startswith("data:image/png;base64,")
    assert setup["otpauth_uri"].startswith("otpauth://totp/Leapvoy:me%40x.com")
    assert len(setup["totp_secret"]) == 32


async def test_wrong_code_does_not_turn_2fa_on(api):
    tokens = await signup(api)
    await api.post("/auth/2fa/setup", headers=bearer(tokens))
    r = await api.post("/auth/2fa/enable", headers=bearer(tokens), json={"code": "000000"})
    assert r.status_code == 400
    assert (await login(api)).status_code == 200  # still password-only


async def test_with_2fa_on_sign_in_needs_the_code(api):
    tokens = await signup(api)
    secret = await turn_on_2fa(api, tokens)
    assert (await api.get("/me", headers=bearer(tokens))).json()["totp_enabled"] is True
    no_code = await login(api)
    assert no_code.status_code == 401 and no_code.json()["detail"] == "totp_required"
    assert (await login(api, code="000000")).status_code == 401
    assert (await login(api, code=pyotp.TOTP(secret).now())).status_code == 200


async def test_turning_2fa_off_needs_password_and_code(api):
    tokens = await signup(api)
    secret = await turn_on_2fa(api, tokens)
    bad = await api.post("/auth/2fa/disable", headers=bearer(tokens), json={"password": "wrong password!!",
                                                                             "code": pyotp.TOTP(secret).now()})
    assert bad.status_code == 401
    ok = await api.post("/auth/2fa/disable", headers=bearer(tokens), json={"password": PW,
                                                                            "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200
    assert (await login(api)).status_code == 200


# --- tokens + devices ---------------------------------------------------------------

async def test_refresh_rotates_and_old_refresh_token_dies(api):
    tokens = await signup(api)
    r = await api.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200 and r.json()["refresh_token"] != tokens["refresh_token"]
    again = await api.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert again.status_code == 401


async def test_each_device_has_its_own_login_and_can_be_logged_out_remotely(api):
    phone = await signup(api, device="Pixel 7")
    laptop = (await login(api, device="Laptop")).json()
    devices = (await api.get("/auth/devices", headers=bearer(laptop))).json()
    assert sorted(d["name"] for d in devices) == ["Laptop", "Pixel 7"]
    phone_id = next(d["id"] for d in devices if d["name"] == "Pixel 7")
    assert (await api.delete(f"/auth/devices/{phone_id}", headers=bearer(laptop))).status_code == 204
    assert (await api.get("/me", headers=bearer(phone))).status_code == 401  # lost phone is locked out
    assert (await api.post("/auth/refresh", json={"refresh_token": phone["refresh_token"]})).status_code == 401
    assert (await api.get("/me", headers=bearer(laptop))).status_code == 200


async def test_logout_ends_this_device_only(api):
    phone = await signup(api, device="Pixel 7")
    laptop = (await login(api, device="Laptop")).json()
    assert (await api.post("/auth/logout", headers=bearer(laptop))).status_code == 204
    assert (await api.get("/me", headers=bearer(laptop))).status_code == 401
    assert (await api.get("/me", headers=bearer(phone))).status_code == 200


async def test_users_cannot_see_or_remove_each_others_devices(api):
    a = await signup(api, "a@x.com")
    b = await signup(api, "b@x.com")
    a_devices = (await api.get("/auth/devices", headers=bearer(a))).json()
    assert len((await api.get("/auth/devices", headers=bearer(b))).json()) == 1
    assert (await api.delete(f"/auth/devices/{a_devices[0]['id']}", headers=bearer(b))).status_code == 404


async def test_no_token_or_bad_token_is_refused(api):
    assert (await api.get("/me")).status_code == 401
    assert (await api.get("/me", headers={"Authorization": "Bearer nonsense"})).status_code == 401
