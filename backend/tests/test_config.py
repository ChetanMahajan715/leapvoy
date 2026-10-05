import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_reads_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/leapvoy")
    assert Settings(_env_file=None).database_url == "postgresql+asyncpg://u:p@db:5432/leapvoy"


def test_missing_database_url_is_an_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
