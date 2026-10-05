"""On a public address (Tailscale Funnel) only the owner may sign up: SIGNUP_MODE=first lets the first account in, then
closes; closed lets nobody in; open (laptop, tests) lets anyone. API docs can be hidden too."""
import httpx

from app.core.config import get_settings
from tests.conftest import requires_db
from tests.test_auth_api import PW, api, secrets  # noqa: F401 (fixtures)

pytestmark = requires_db


async def sign_up(api, email):
    return await api.post("/auth/signup", json={"email": email, "password": PW, "device_name": "t"})


async def test_first_mode_lets_only_the_owner_sign_up(api, monkeypatch):
    monkeypatch.setenv("SIGNUP_MODE", "first")
    get_settings.cache_clear()
    assert (await sign_up(api, "owner@x.com")).status_code == 200
    r = await sign_up(api, "stranger@x.com")
    assert r.status_code == 403 and "closed" in r.json()["detail"].lower()
    assert (await api.post("/auth/login", json={"email": "owner@x.com", "password": PW, "device_name": "t2"})).status_code == 200
    get_settings.cache_clear()


async def test_closed_mode_lets_nobody_sign_up(api, monkeypatch):
    monkeypatch.setenv("SIGNUP_MODE", "closed")
    get_settings.cache_clear()
    assert (await sign_up(api, "a@x.com")).status_code == 403
    get_settings.cache_clear()


def test_api_docs_can_be_hidden(monkeypatch):
    from app.main import docs_options

    assert docs_options() == {}
    monkeypatch.setenv("API_DOCS", "false")
    get_settings.cache_clear()
    assert docs_options() == {"docs_url": None, "redoc_url": None, "openapi_url": None}
    get_settings.cache_clear()
