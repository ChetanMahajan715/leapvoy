import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.session import get_engine
from app.main import app
from tests.conftest import TEST_DATABASE_URL, requires_db


async def get_health(engine):
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_health_is_503_when_db_unreachable():
    # port 1 is closed → connection refused
    engine = create_async_engine("postgresql+asyncpg://x:y@127.0.0.1:1/x")
    r = await get_health(engine)
    assert r.status_code == 503
    assert r.json() == {"status": "error", "db": "down"}


@requires_db
async def test_health_ok_reports_pgvector_version(migrated_db):
    r = await get_health(create_async_engine(TEST_DATABASE_URL))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["db"] == "ok"
    assert body["pgvector"]  # e.g. "0.8.1"
