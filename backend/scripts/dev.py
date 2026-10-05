"""Laptop dev runner: start local Postgres + pgvector (pgserver, no Docker), migrate, run a command.

  uv run python scripts/dev.py python -m app.telegram.cli channels --email me@x.com
  uv run python scripts/dev.py python -m app.workers.telegram_reader

Data lives in <repo>/.pgdata. The DB stops when the command exits.
"""

import os
import subprocess
import sys
from pathlib import Path

import pgserver

BACKEND = Path(__file__).resolve().parents[1]

if len(sys.argv) < 2:
    sys.exit(__doc__)

srv = pgserver.get_server(BACKEND.parent / ".pgdata")  # port changes per start → pass URL via env
if "leapvoy" not in srv.psql("SELECT datname FROM pg_database").split():
    srv.psql("CREATE DATABASE leapvoy")
env = {**os.environ, "DATABASE_URL": srv.get_uri("leapvoy").replace("postgresql://", "postgresql+asyncpg://", 1)}
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True)
cmd = [sys.executable if sys.argv[1] == "python" else sys.argv[1], *sys.argv[2:]]
sys.exit(subprocess.run(cmd, cwd=BACKEND, env=env).returncode)
