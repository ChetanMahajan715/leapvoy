"""sends: to_emails (one email to every HR address of a post); to_email stays = the first one

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sends", sa.Column("to_emails", ARRAY(sa.Text()), server_default="{}", nullable=False))
    op.execute("UPDATE sends SET to_emails = ARRAY[to_email]")
    op.create_index("ix_sends_to_emails", "sends", ["to_emails"], postgresql_using="gin")  # "emailed this HR?" checks


def downgrade() -> None:
    op.drop_index("ix_sends_to_emails", table_name="sends")
    op.drop_column("sends", "to_emails")
