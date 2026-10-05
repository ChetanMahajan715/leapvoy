"""chat: chats, messages (full-text search), memories, pending actions

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def user_fk() -> sa.ForeignKey:
    return sa.ForeignKey("users.id", ondelete="CASCADE")


def now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), user_fk(), nullable=False),
        sa.Column("title", sa.Text(), server_default="New chat", nullable=False),
        sa.Column("pinned", sa.Boolean(), server_default="false", nullable=False),
        now("created_at"),
        now("updated_at"),
    )
    op.create_index("ix_chats_user_updated", "chats", ["user_id", "updated_at"])
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.Uuid(), user_fk(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("cards", JSONB(), server_default="[]", nullable=False),
        sa.Column("search", TSVECTOR(), sa.Computed("to_tsvector('simple', content)", persisted=True)),
        now("created_at"),
    )
    op.create_index("ix_messages_search", "messages", ["search"], postgresql_using="gin")
    op.create_table(
        "memories",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), user_fk(), nullable=False, index=True),
        sa.Column("text", sa.Text(), nullable=False),
        now("created_at"),
    )
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), user_fk(), nullable=False, index=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("result", sa.Text()),
        now("created_at"),
    )


def downgrade() -> None:
    op.drop_table("pending_actions")
    op.drop_table("memories")
    op.drop_table("messages")
    op.drop_table("chats")
