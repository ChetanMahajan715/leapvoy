import httpx

from app.main import app


async def preflight(origin):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        return await c.options("/auth/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})


async def test_web_app_origin_is_allowed():
    r = await preflight("http://localhost:8081")
    assert r.headers.get("access-control-allow-origin") == "http://localhost:8081"


async def test_other_sites_are_not_allowed():
    r = await preflight("https://evil.example")
    assert "access-control-allow-origin" not in r.headers


async def test_chat_stream_preflight_allows_the_sse_client_headers():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.options("/chat/stream", headers={
            "Origin": "http://localhost:8081", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,cache-control,content-type,x-requested-with"})
    assert r.status_code == 200
