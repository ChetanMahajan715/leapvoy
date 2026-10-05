"""telegram accounts, channels, posts

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def user_fk() -> sa.ForeignKey:
    return sa.ForeignKey("users.id", ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "telegram_accounts",
        sa.Column("user_id", sa.Uuid(), user_fk(), primary_key=True),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("session_enc", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "channels",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), user_fk(), nullable=False),
        sa.Column("tg_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("username", sa.Text()),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_message_id", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "tg_chat_id"),
    )
    op.create_table(
        "posts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), user_fk(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel_id", "tg_message_id"),
    )
    op.create_index("ix_posts_user_posted", "posts", ["user_id", "posted_at"])


def downgrade() -> None:
    op.drop_table("posts")
    op.drop_table("channels")
    op.drop_table("telegram_accounts")
