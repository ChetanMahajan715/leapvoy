from functools import lru_cache
from pathlib import Path

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# repo-root .env (absent inside Docker, where compose passes env vars)
ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore", env_ignore_empty=True)

    database_url: str  # postgresql+asyncpg://user:pass@host:5432/db
    log_level: str = "INFO"
    log_json: bool = False  # True on the server
    master_key: str | None = None  # base64 32 bytes; encrypts secrets at rest
    jwt_secret: str | None = None  # signs app login tokens (separate from master_key)
    # Leapvoy's own mailbox for system emails (password reset codes), Gmail + App Password
    system_email: str | None = None
    system_email_password: str | None = None
    # web app origins allowed to call the API from a browser (dev: Expo web; prod: the Tailscale https URL)
    cors_origins: list[str] = ["http://localhost:8081", "http://localhost:8082"]
    # Public address (Tailscale Funnel): "first" = only the first account may sign up, then sign-ups close by
    # themselves; "closed" = nobody; "open" = anyone (laptop, tests)
    signup_mode: Literal["open", "first", "closed"] = "open"
    api_docs: bool = True  # /docs and /openapi.json; off on the public server
    telegram_api_id: int | None = None  # from my.telegram.org
    telegram_api_hash: str | None = None

    # LLMs (free tiers). Models get retired → names live here, not in code.
    groq_api_key: str | None = None
    mistral_api_key: str | None = None  # 2nd provider (free "Experiment" plan allows the Ministral models)
    gemini_api_key: str | None = None  # 3rd provider (Google AI Studio free key)
    ollama_url: str | None = None  # optional offline backup on the server, e.g. http://ollama:11434
    llm_small: str = "groq/openai/gpt-oss-20b"  # extraction, chat commands, titles
    llm_large: str = "groq/openai/gpt-oss-120b"  # fit check, email writing
    # each Groq model has its own free limit → all three before Mistral / Ollama (main model is skipped as a duplicate)
    llm_fallbacks: list[str] = ["groq/qwen/qwen3.8-27b", "groq/openai/gpt-oss-20b", "groq/openai/gpt-oss-120b",
                                "mistral/ministral-14b-latest", "gemini/gemini-3.8-flash", "gemini/gemini-3.5-flash",
                                "ollama/ministral-3b"]  # Gemini: newest Flash first; 3.5 when it is overloaded (503)
    groq_daily_tokens: int = 200_000  # Groq free tier, per model, rolling 24 h
    chat_reserve: float = 0.2  # the background pauses when every Groq model has less than this share left
    match_threshold: float = 0.645  # min resume↔post cosine; provisional from 20 real posts (29 Sep), re-tune on golden set


@lru_cache
def get_settings() -> Settings:
    return Settings()
