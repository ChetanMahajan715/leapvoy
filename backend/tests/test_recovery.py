from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from sqlalchemy import update

from app.accounts import recovery
from app.core.config import get_settings
from app.db.models import PasswordReset
from tests.conftest import requires_db
from tests.test_auth_api import PW, api, bearer, login, secrets, signup, turn_on_2fa  # noqa: F401 (fixtures)

pytestmark = requires_db
NEW_PW = "brand new password 42"


@pytest.fixture
def mailbox(monkeypatch):
    """System email configured; reset emails are captured instead of sent."""
    monkeypatch.setenv("SYSTEM_EMAIL", "leapvoy@gmail.com")
    monkeypatch.setenv("SYSTEM_EMAIL_PASSWORD", "test app password")
    get_settings.cache_clear()
    sent: list[tuple[str, str]] = []

    async def fake_send(to: str, code: str) -> None:
        sent.append((to, code))

    monkeypatch.setattr(recovery, "send_code_email", fake_send)
    return sent


async def test_without_system_email_reset_says_so(api, monkeypatch):
    unset = get_settings().model_copy(update={"system_email_password": None})  # whatever the real .env has
    monkeypatch.setattr(recovery, "get_settings", lambda: unset)
    r = await forgot(api)
    assert r.status_code == 503 and "not set up" in r.json()["detail"]


async def forgot(api, email="me@x.com"):
    return await api.post("/auth/password/forgot", json={"email": email})


async def reset(api, code, email="me@x.com", password=NEW_PW):
    return await api.post("/auth/password/reset", json={"email": email, "code": code, "new_password": password})


# --- forgot password ------------------------------------------------------------------

async def test_forgot_password_emails_a_6_digit_code(api, mailbox):
    await signup(api)
    assert (await forgot(api)).status_code == 200
    [(to, code)] = mailbox
    assert to == "me@x.com" and len(code) == 6 and code.isdigit()


async def test_unknown_email_gets_the_same_answer_and_no_mail(api, mailbox):
    r = await forgot(api, "nobody@x.com")
    assert r.status_code == 200 and mailbox == []


async def test_code_sets_a_new_password_and_logs_out_every_device(api, mailbox):
    old = await signup(api)
    await forgot(api)
    assert (await reset(api, mailbox[0][1])).status_code == 200
    assert (await login(api)).status_code == 401  # old password gone
    assert (await login(api, password=NEW_PW)).status_code == 200
    assert (await api.get("/me", headers=bearer(old))).status_code == 401  # other devices logged out


async def test_wrong_code_is_refused_and_code_dies_after_5_tries(api, mailbox):
    await signup(api)
    await forgot(api)
    for _ in range(5):
        assert (await reset(api, "000000")).status_code == 400
    assert (await reset(api, mailbox[0][1])).status_code == 400  # locked after 5 wrong tries


async def test_code_expires_after_15_minutes(api, mailbox, sm):
    await signup(api)
    await forgot(api)
    async with sm() as s:
        await s.execute(update(PasswordReset).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await s.commit()
    assert (await reset(api, mailbox[0][1])).status_code == 400


async def test_code_works_only_once_and_newest_code_wins(api, mailbox):
    await signup(api)
    await forgot(api)
    await forgot(api)
    first, second = mailbox[0][1], mailbox[1][1]
    assert (await reset(api, first)).status_code == 400  # replaced by the newer code
    assert (await reset(api, second)).status_code == 200
    assert (await reset(api, second, password="another password 99")).status_code == 400


async def test_password_reset_keeps_2fa_on(api, mailbox):
    tokens = await signup(api)
    await turn_on_2fa(api, tokens)
    await forgot(api)
    await reset(api, mailbox[0][1])
    r = await login(api, password=NEW_PW)
    assert r.status_code == 401 and r.json()["detail"] == "totp_required"


# --- backup codes ------------------------------------------------------------------------

async def enable_with_codes(api, tokens):
    setup = (await api.post("/auth/2fa/setup", headers=bearer(tokens))).json()
    r = await api.post("/auth/2fa/enable", headers=bearer(tokens), json={"code": pyotp.TOTP(setup["totp_secret"]).now()})
    return setup["totp_secret"], r.json()["backup_codes"]


async def test_turning_on_2fa_gives_10_backup_codes(api):
    _, codes = await enable_with_codes(api, await signup(api))
    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) == 9 and c[4] == "-" for c in codes)


async def test_backup_code_signs_in_once(api):
    _, codes = await enable_with_codes(api, await signup(api))
    assert (await login(api, code=codes[0])).status_code == 200
    assert (await login(api, code=codes[0])).status_code == 401  # used up
    assert (await login(api, code=codes[1].upper())).status_code == 200


async def test_backup_code_can_turn_2fa_off_when_phone_is_lost(api):
    tokens = await signup(api)
    _, codes = await enable_with_codes(api, tokens)
    r = await api.post("/auth/2fa/disable", headers=bearer(tokens), json={"password": PW, "code": codes[0]})
    assert r.status_code == 200
    assert (await login(api)).status_code == 200


# --- server reset (last resort) -----------------------------------------------------------

async def test_server_reset_sets_password_turns_2fa_off_and_logs_out(api, sm):
    tokens = await signup(api)
    await turn_on_2fa(api, tokens)
    async with sm() as s:
        assert await recovery.admin_reset(s, "me@x.com", NEW_PW) is True
        assert await recovery.admin_reset(s, "nobody@x.com", NEW_PW) is False
    assert (await api.get("/me", headers=bearer(tokens))).status_code == 401
    assert (await login(api, password=NEW_PW)).status_code == 200  # no code needed any more
