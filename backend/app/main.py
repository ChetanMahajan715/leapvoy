from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.auth import router as auth_router
from app.api.chat_stream import router as chat_stream_router
from app.api.chats import router as chats_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.models import router as models_router
from app.api.senders import router as senders_router
from app.api.settings import router as settings_router
from app.api.stats import router as stats_router
from app.api.telegram import router as telegram_router
from app.api.template import router as template_router
from app.api.notifications import router as notifications_router
from app.api.ratelimit import limiter
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import get_engine
from app.llm import usage


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    usage.install()  # record AI tokens so the background leaves the user's chat a reserve
    yield
    await get_engine().dispose()


def docs_options() -> dict:
    """The public server hides the API docs (API_DOCS=false), so strangers can't browse the API's map."""
    return {} if get_settings().api_docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}


app = FastAPI(title="Leapvoy", lifespan=lifespan, **docs_options())
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "Cache-Control", "X-Requested-With"],  # last two: chat SSE client
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(chats_router)
app.include_router(chat_stream_router)
app.include_router(jobs_router)
app.include_router(models_router)
app.include_router(settings_router)
app.include_router(senders_router)
app.include_router(telegram_router)
app.include_router(stats_router)
app.include_router(template_router)
app.include_router(notifications_router)
