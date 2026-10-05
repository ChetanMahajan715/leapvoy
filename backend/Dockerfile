# Build context = repo root (uv workspace: root pyproject.toml + uv.lock).
# python:3.12-slim and uv images are multi-arch → builds on Oracle ARM64 too.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
# OpenCV (used by RapidOCR, photo / scanned-PDF text) needs these system libraries; the slim image lacks them
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libxcb1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=backend/pyproject.toml,target=backend/pyproject.toml \
    uv sync --locked --no-dev --package leapvoy-backend

COPY backend /app/backend
COPY docs/templates /app/docs/templates
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app/backend

EXPOSE 8000
# --proxy-headers: behind nginx, the real client address comes from X-Forwarded-For (per-person rate limits)
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*"]
