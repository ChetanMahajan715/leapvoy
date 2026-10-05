"""users.delete_after (delete account with a 7-day grace) + day_stats (daily counts kept after old posts are cleaned).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("delete_after", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "day_stats",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("posts", sa.Integer(), nullable=False),
        sa.Column("checked", sa.Integer(), nullable=False),
        sa.Column("fits", JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("day_stats")
    op.drop_column("users", "delete_after")
