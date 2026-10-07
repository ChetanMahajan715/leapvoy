import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBED_DIM = 384  # BAAI/bge-small-en-v1.5


def _texts() -> Mapped[list[str]]:
    return mapped_column(ARRAY(Text), default=list, server_default="{}")


class Base(DeclarativeBase):
    pass


class User(Base):
    """Every other table references users.id (per-user data scoping)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lower-cased
    password_hash: Mapped[str] = mapped_column(String(255))  # argon2; "!" = not signed up yet (made by a CLI)
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # AES-GCM, aad = user id
    totp_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    backup_codes: Mapped[list[str]] = _texts()  # keyed hashes of unused 2FA backup codes
    # set = deletion asked: everything is paused; after this time the account and all its data are deleted
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasswordReset(Base):
    """Forgot-password code sent by email: stored hashed, 15 min, 5 tries, one use; a newer code replaces it."""

    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Device(Base):
    """One logged-in phone/laptop. refresh_hash = sha256 of its refresh token (rotated on every refresh).
    revoked_at set by logout / remote logout → its tokens stop working immediately."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    push_token: Mapped[str | None] = mapped_column(String(200))  # Expo push token of this phone (APK only)


class Notification(Base):
    """In-app inbox (web + phone). push: pending → sent / none (no phone, below the chosen fit, or kind muted)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    push: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hidden: Mapped[bool] = mapped_column(default=False, server_default="false")  # deleted by the user
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Profile(Base):
    """Per-user profile values used by fit checks and email templates (seeded from profile.seed.json)."""

    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TelegramAccount(Base):
    """One connected Telegram login per user. Session is AES-GCM encrypted (aad = user_id)."""

    __tablename__ = "telegram_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    phone: Mapped[str] = mapped_column(String(32))
    session_enc: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Channel(Base):
    """A channel/group the user joined. last_message_id = catch-up cursor."""

    __tablename__ = "channels"
    __table_args__ = (UniqueConstraint("user_id", "tg_chat_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tg_chat_id: Mapped[int] = mapped_column(BigInteger)  # Telethon "marked" id, e.g. -100123…
    title: Mapped[str] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    last_message_id: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Post(Base):
    """A saved Telegram post. `stage` tracks the AI pipeline: new → skipped | matched → extracted → scored (| error)."""

    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("channel_id", "tg_message_id"),
        Index("ix_posts_user_posted", "user_id", "posted_at"),
        Index("ix_posts_user_stage", "user_id", "stage"),
        Index("ix_posts_user_hash", "user_id", "text_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    tg_message_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    stage: Mapped[str] = mapped_column(String(16), default="new", server_default="new")
    skip_reason: Mapped[str | None] = mapped_column(Text)  # no_email | duplicate | low_match | no_valid_job | error msg
    text_hash: Mapped[str | None] = mapped_column(String(64))
    match_score: Mapped[float | None]
    emails: Mapped[list[str]] = _texts()  # found by the prefilter (ground truth for LLM output)
    links: Mapped[list[str]] = _texts()  # apply links found by the prefilter (ground truth for LLM output)
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")


class Resume(Base):
    """Every uploaded version is kept; exactly one active per user is used for matching."""

    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    pdf: Mapped[bytes | None] = mapped_column(LargeBinary)  # attached to emails
    filename: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResumeChunk(Base):
    """embed_model + embed_lib saved per vector → changing the model means re-embedding, never mixing."""

    __tablename__ = "resume_chunks"
    __table_args__ = (
        Index(
            "ix_resume_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"))
    idx: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(EMBED_DIM))
    embed_model: Mapped[str] = mapped_column(Text)
    embed_lib: Mapped[str] = mapped_column(Text)


class Job(Base):
    """One job extracted from a post (a post can hold several). Fit fields filled by the fit stage."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("post_id", "idx"),
        Index("ix_jobs_user_score", "user_id", "fit_score"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    idx: Mapped[int]
    company: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    hr_emails: Mapped[list[str]] = _texts()
    apply_links: Mapped[list[str]] = _texts()
    apply_method: Mapped[str] = mapped_column(String(8), default="email", server_default="email")  # email | link
    hr_name: Mapped[str | None] = mapped_column(Text)
    experience: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    work_mode: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown")
    must_have_skills: Mapped[list[str]] = _texts()
    apply_instructions: Mapped[str | None] = mapped_column(Text)
    salary: Mapped[str | None] = mapped_column(Text)
    fit_score: Mapped[int | None]
    verdict: Mapped[str | None] = mapped_column(String(16))
    fit_rows: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    matched_skills: Mapped[list[str]] = _texts()
    gaps: Mapped[list[str]] = _texts()
    flags: Mapped[list[str]] = _texts()
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))  # who scored it
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Draft(Base):
    """The application email for one job. resume_id = the resume version it was written from
    (a newer active resume makes the draft outdated). status: draft | needs_review | approved."""

    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"))
    template_name: Mapped[str] = mapped_column(Text)
    to_emails: Mapped[list[str]] = _texts()
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    edited: Mapped[bool] = mapped_column(default=False, server_default="false")  # the user's own words: sent as-is
    issues: Mapped[list[str]] = _texts()  # checks that still fail after rewrites (unsupported skills, length)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SenderAccount(Base):
    """An email ID the user sends from. App Password is AES-GCM encrypted (aad = user_id)."""

    __tablename__ = "sender_accounts"
    __table_args__ = (UniqueConstraint("user_id", "email"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    provider: Mapped[str] = mapped_column(String(16))  # gmail | outlook | zoho | yahoo
    password_enc: Mapped[bytes] = mapped_column(LargeBinary)
    daily_limit: Mapped[int] = mapped_column(default=20, server_default="20")
    is_default: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DayStats(Base):
    """One India day's counts, saved before old posts are cleaned up, so Stats stay right for long periods."""

    __tablename__ = "day_stats"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    posts: Mapped[int]
    checked: Mapped[int]
    fits: Mapped[dict] = mapped_column(JSONB)  # {"TOP PRIORITY": 2, "STRONG MATCH": 1, ...}


class EmailTemplate(Base):
    """The user's own email template versions (plain text with {tags}). None active = the approved default."""

    __tablename__ = "email_templates"
    __table_args__ = (UniqueConstraint("user_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    version: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    test_mode: Mapped[bool] = mapped_column(default=True, server_default="true")  # every mail → user's own inbox
    notify: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")  # notification choices
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Send(Base):
    """Send queue + history. subject/body are frozen at approval. send_key makes each email unique (no double send).
    status: scheduled → sending → sent | failed | cancelled | unknown (crashed mid-send: never auto-retried)."""

    __tablename__ = "sends"
    __table_args__ = (
        Index("ix_sends_status_at", "status", "send_at"),
        Index("ix_sends_to_emails", "to_emails", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id", ondelete="SET NULL"))
    sender_id: Mapped[int] = mapped_column(ForeignKey("sender_accounts.id", ondelete="CASCADE"))
    to_email: Mapped[str] = mapped_column(String(320))  # the first of to_emails (lists, older rows)
    to_emails: Mapped[list[str]] = _texts()  # every HR address this one email goes to (all in "To")
    send_key: Mapped[str] = mapped_column(Text, unique=True)
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="scheduled", server_default="scheduled")
    test_mode: Mapped[bool]
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(Text)
    hidden: Mapped[bool] = mapped_column(default=False, server_default="false")  # deleted from the lists (still counts)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reply_snippet: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DoNotContact(Base):
    __tablename__ = "do_not_contact"
    __table_args__ = (UniqueConstraint("user_id", "email"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(320))
    reason: Mapped[str] = mapped_column(Text)  # replied | not interested | manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Chat(Base):
    """A saved conversation (incognito chats are never stored)."""

    __tablename__ = "chats"
    __table_args__ = (Index("ix_chats_user_updated", "user_id", "updated_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text, default="New chat", server_default="New chat")
    pinned: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    """cards = UI blocks shown under the text, e.g. [{"type": "jobs", "job_ids": [1, 2]}]; rendered with live status."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_search", "search", postgresql_using="gin"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    cards: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    search: Mapped[Any] = mapped_column(TSVECTOR, Computed("to_tsvector('simple', content)", persisted=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Memory(Base):
    """A preference the user asked Leapvoy to remember ("prefer 10 AM"). No screen yet: the chat uses them (planned: Settings)."""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingAction(Base):
    """Something the assistant proposed that sends/cancels/moves an email. Runs only when the user taps Confirm.
    kind: schedule | cancel | reschedule · status: pending → done | dismissed | failed"""

    __tablename__ = "pending_actions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    result: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LlmUsage(Base):
    """Tokens used per AI call (all users share the app's free API keys), the background pauses before the
    free daily allowance runs out, so chat always has some left."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    model: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int]


class LlmLimit(Base):
    """Last time a model said 'limit reached' and when it can be used again (model picker: 'No usage left')."""

    __tablename__ = "llm_limits"

    model: Mapped[str] = mapped_column(Text, primary_key=True)
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    daily: Mapped[bool] = mapped_column(default=False)  # the day's allowance (vs a short per-minute pause)
