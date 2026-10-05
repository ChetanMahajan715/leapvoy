"""sending: sender accounts, user settings (test mode on), send queue, do-not-contact

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def user_fk() -> sa.ForeignKey:
    return sa.ForeignKey("users.id", ondelete="CASCADE")


def ts(name: str, nullable: bool = False, now: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now() if now else None, nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "sender_accounts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), user_fk(), nullable=False, index=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("password_enc", sa.LargeBinary(), nullable=False),
        sa.Column("daily_limit", sa.Integer(), server_default="20", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        ts("created_at", now=True),
        sa.UniqueConstraint("user_id", "email"),
    )
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Uuid(), user_fk(), primary_key=True),
        sa.Column("test_mode", sa.Boolean(), server_default="true", nullable=False),
        ts("updated_at", now=True),
    )
    op.create_table(
        "sends",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), user_fk(), nullable=False, index=True),
        sa.Column("job_id", sa.BigInteger(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_id", sa.BigInteger(), sa.ForeignKey("drafts.id", ondelete="SET NULL")),
        sa.Column("sender_id", sa.BigInteger(), sa.ForeignKey("sender_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_email", sa.String(320), nullable=False),
        sa.Column("send_key", sa.Text(), nullable=False, unique=True),
        ts("send_at"),
        sa.Column("status", sa.String(16), server_default="scheduled", nullable=False),
        sa.Column("test_mode", sa.Boolean(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("message_id", sa.Text()),
        ts("sent_at", nullable=True),
        ts("replied_at", nullable=True),
        sa.Column("reply_snippet", sa.Text()),
        ts("created_at", now=True),
    )
    op.create_index("ix_sends_status_at", "sends", ["status", "send_at"])
    op.create_table(
        "do_not_contact",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), user_fk(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        ts("created_at", now=True),
        sa.UniqueConstraint("user_id", "email"),
    )


def downgrade() -> None:
    op.drop_table("do_not_contact")
    op.drop_table("sends")
    op.drop_table("user_settings")
    op.drop_table("sender_accounts")
