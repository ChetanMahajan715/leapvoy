"""llm_limits: when a model hit its free limit and when it is usable again (model picker shows 'No usage left')

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_limits",
        sa.Column("model", sa.Text(), primary_key=True),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("daily", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_table("llm_limits")
