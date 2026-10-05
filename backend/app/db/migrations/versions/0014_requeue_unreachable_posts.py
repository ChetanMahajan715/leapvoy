"""Re-queue posts marked 'AI check failed' only because no AI could be reached (1 Oct: laptop offline).
Such failures are no longer counted against a post (router.AIUnreachable); this puts the old ones back in line.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-02
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE posts SET stage = 'new', attempts = 0, skip_reason = NULL "
               "WHERE stage = 'error' AND skip_reason = 'error: LLMUnavailable'")


def downgrade() -> None:
    pass  # data fix only
