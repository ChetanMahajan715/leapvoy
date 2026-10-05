"""llm_usage: tokens per AI call, so the background keeps a reserve of the free daily allowance for chat

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
    )
    op.create_index("ix_llm_usage_at", "llm_usage", ["at"])


def downgrade() -> None:
    op.drop_table("llm_usage")
