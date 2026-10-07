"""Emails the user edited by hand; deleting emails from the Scheduled / Sent lists and notifications from the inbox.

Deleting hides a row instead of removing it: a sent email still counts for "you emailed this address 3 days ago",
and a deleted job alert never comes back as new after a re-check.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("drafts", sa.Column("edited", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("sends", sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("notifications", sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("notifications", "hidden")
    op.drop_column("sends", "hidden")
    op.drop_column("drafts", "edited")
