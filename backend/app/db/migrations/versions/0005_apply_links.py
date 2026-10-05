"""apply links: posts.links, jobs.apply_links + apply_method; re-queue posts dropped for having no email

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def texts(name: str) -> sa.Column:
    return sa.Column(name, ARRAY(sa.Text()), server_default="{}", nullable=False)


def upgrade() -> None:
    op.add_column("posts", texts("links"))
    op.add_column("jobs", texts("apply_links"))
    op.add_column("jobs", sa.Column("apply_method", sa.String(8), server_default="email", nullable=False))
    # link / Google-Form posts are now kept → give the ones dropped earlier another pass
    op.execute("UPDATE posts SET stage = 'new', skip_reason = NULL WHERE stage = 'skipped' AND skip_reason = 'no_email'")


def downgrade() -> None:
    op.drop_column("jobs", "apply_method")
    op.drop_column("jobs", "apply_links")
    op.drop_column("posts", "links")
