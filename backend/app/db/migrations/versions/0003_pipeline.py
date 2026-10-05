"""pipeline: post stages, resumes + chunk embeddings, jobs

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def user_fk() -> sa.ForeignKey:
    return sa.ForeignKey("users.id", ondelete="CASCADE")


def texts(name: str) -> sa.Column:
    return sa.Column(name, ARRAY(sa.Text()), server_default="{}", nullable=False)


def upgrade() -> None:
    op.add_column("posts", sa.Column("stage", sa.String(16), server_default="new", nullable=False))
    op.add_column("posts", sa.Column("skip_reason", sa.Text()))
    op.add_column("posts", sa.Column("text_hash", sa.String(64)))
    op.add_column("posts", sa.Column("match_score", sa.Float()))
    op.add_column("posts", texts("emails"))
    op.add_column("posts", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
    op.create_index("ix_posts_user_stage", "posts", ["user_id", "stage"])
    op.create_index("ix_posts_user_hash", "posts", ["user_id", "text_hash"])

    op.create_table(
        "resumes",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), user_fk(), nullable=False, index=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "resume_chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), user_fk(), nullable=False, index=True),
        sa.Column("resume_id", sa.BigInteger(), sa.ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", VECTOR(384), nullable=False),
        sa.Column("embed_model", sa.Text(), nullable=False),
        sa.Column("embed_lib", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_resume_chunks_embedding",
        "resume_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), user_fk(), nullable=False),
        sa.Column("post_id", sa.BigInteger(), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        texts("hr_emails"),
        sa.Column("hr_name", sa.Text()),
        sa.Column("experience", sa.Text()),
        sa.Column("location", sa.Text()),
        sa.Column("work_mode", sa.String(16), server_default="unknown", nullable=False),
        texts("must_have_skills"),
        sa.Column("apply_instructions", sa.Text()),
        sa.Column("salary", sa.Text()),
        sa.Column("fit_score", sa.Integer()),
        sa.Column("verdict", sa.String(16)),
        sa.Column("fit_rows", JSONB()),
        texts("matched_skills"),
        texts("gaps"),
        texts("flags"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("post_id", "idx"),
    )
    op.create_index("ix_jobs_user_score", "jobs", ["user_id", "fit_score"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("resume_chunks")
    op.drop_table("resumes")
    op.drop_index("ix_posts_user_hash", table_name="posts")
    op.drop_index("ix_posts_user_stage", table_name="posts")
    for col in ("attempts", "emails", "match_score", "text_hash", "skip_reason", "stage"):
        op.drop_column("posts", col)
