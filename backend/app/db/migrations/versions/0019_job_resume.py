"""Which resume scored each job (shown as "Checked with: <resume>", re-checked when the primary resume changes).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("resume_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("jobs_resume_id_fkey", "jobs", "resumes", ["resume_id"], ["id"], ondelete="SET NULL")
    # jobs scored before this column existed were scored with the resume that is primary now
    op.execute("UPDATE jobs j SET resume_id = r.id FROM resumes r "
               "WHERE r.user_id = j.user_id AND r.is_active AND j.fit_score IS NOT NULL")


def downgrade() -> None:
    op.drop_constraint("jobs_resume_id_fkey", "jobs", type_="foreignkey")
    op.drop_column("jobs", "resume_id")
