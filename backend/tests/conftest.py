import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import NullPool, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND = Path(__file__).resolve().parents[1]

# Throwaway test DB (migrations are dropped and re-applied there).
# TEST_DATABASE_URL wins (e.g. Docker/CI); otherwise start a local Postgres+pgvector
# via pgserver (dev dep, no Docker/admin needed), data in <repo>/.pgdata.
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    try:
        import pgserver
    except ImportError:
        pass
    else:
        _srv = pgserver.get_server(BACKEND.parent / ".pgdata")  # stopped when tests end
        if "leapvoy_test" not in _srv.psql("SELECT datname FROM pg_database"):
            _srv.psql("CREATE DATABASE leapvoy_test")
        TEST_DATABASE_URL = _srv.get_uri("leapvoy_test").replace("postgresql://", "postgresql+asyncpg://", 1)

requires_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="needs Postgres: set TEST_DATABASE_URL or install dev deps (pgserver)",
)


def alembic(*args):
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, check=True)


@pytest.fixture
def migrated_db():
    alembic("downgrade", "base")
    alembic("upgrade", "head")


@pytest.fixture(scope="session")
def schema():
    alembic("upgrade", "head")


@pytest.fixture
async def sm(schema):
    """Sessionmaker on an emptied test DB (all user data + AI usage wiped before each test)."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users, llm_usage, llm_limits CASCADE"))  # llm_*: app-wide, not per user
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def db(sm):
    async with sm() as s:
        yield s
