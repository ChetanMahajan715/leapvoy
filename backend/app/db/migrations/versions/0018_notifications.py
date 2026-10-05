"""Notifications: in-app inbox, Expo push token per device, notification choices per user.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("push_token", sa.String(200), nullable=True))
    op.add_column("user_settings", sa.Column("notify", JSONB(), nullable=False, server_default="{}"))
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("push", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_pending", "notifications", ["push"], postgresql_where=sa.text("push = 'pending'"))


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_column("user_settings", "notify")
    op.drop_column("devices", "push_token")
