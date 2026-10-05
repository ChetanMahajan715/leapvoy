"""drafts + resume PDF (for attaching)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def texts(name: str) -> sa.Column:
    return sa.Column(name, ARRAY(sa.Text()), server_default="{}", nullable=False)


def upgrade() -> None:
    op.add_column("resumes", sa.Column("pdf", sa.LargeBinary()))
    op.add_column("resumes", sa.Column("filename", sa.Text()))
    op.create_table(
        "drafts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("job_id", sa.BigInteger(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("resume_id", sa.BigInteger(), sa.ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_name", sa.Text(), nullable=False),
        texts("to_emails"),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        texts("issues"),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("drafts")
    op.drop_column("resumes", "filename")
    op.drop_column("resumes", "pdf")
