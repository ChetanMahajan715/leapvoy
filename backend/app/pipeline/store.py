"""DB access for the pipeline. Every query is scoped by user_id or by a post already scoped to one."""

import uuid
from datetime import datetime

from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, Post, User
from app.llm.schemas import FitCheck, JobPost

PENDING = ("new", "matched", "extracted")  # stages that still have work to do
MAX_ATTEMPTS = 3


async def next_posts(
    s: AsyncSession, user_id: uuid.UUID, limit: int, since: datetime | None = None, until: datetime | None = None
) -> list[int]:
    """Oldest first, so an original post is always processed before its reposts. Optional posted_at range."""
    q = select(Post.id).where(Post.user_id == user_id, Post.stage.in_(PENDING))
    if since:
        q = q.where(Post.posted_at >= since)
    if until:
        q = q.where(Post.posted_at < until)
    return list((await s.execute(q.order_by(Post.id).limit(limit))).scalars())


async def users_with_pending(s: AsyncSession) -> list[uuid.UUID]:
    return list((await s.execute(select(Post.user_id).join(User, User.id == Post.user_id)
                                 .where(Post.stage.in_(PENDING), User.delete_after.is_(None)).distinct())).scalars())


async def update_post(s: AsyncSession, post_id: int, **fields) -> None:
    await s.execute(update(Post).where(Post.id == post_id).values(**fields))
    await s.commit()


async def is_repost(s: AsyncSession, post: Post, text_hash: str) -> bool:
    earlier = select(Post.id).where(Post.user_id == post.user_id, Post.text_hash == text_hash, Post.id < post.id)
    return bool((await s.execute(select(exists(earlier)))).scalar())


async def replace_jobs(s: AsyncSession, post: Post, jobs: list[JobPost]) -> None:
    """Idempotent: a retried extraction replaces rows instead of duplicating them."""
    await s.execute(delete(Job).where(Job.post_id == post.id))
    s.add_all(
        Job(
            user_id=post.user_id,
            post_id=post.id,
            idx=i,
            company=j.company,
            role=j.role,
            hr_emails=j.hr_emails,
            apply_links=j.apply_links,
            apply_method="email" if j.hr_emails else "link",
            hr_name=j.hr_name,
            experience=j.experience,
            location=j.location,
            work_mode=j.work_mode,
            must_have_skills=j.must_have_skills,
            apply_instructions=j.apply_instructions,
            salary=j.salary_or_stipend,
        )
        for i, j in enumerate(jobs)
    )
    await s.execute(update(Post).where(Post.id == post.id).values(stage="extracted", skip_reason=None))
    await s.commit()


async def unscored_jobs(s: AsyncSession, post_id: int) -> list[Job]:
    q = select(Job).where(Job.post_id == post_id, Job.fit_score.is_(None)).order_by(Job.idx)
    return list((await s.execute(q)).scalars())


async def save_fit(s: AsyncSession, job_id: int, fit: FitCheck, resume_id: int | None = None) -> None:
    await s.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(
            resume_id=resume_id,
            fit_score=fit.score,
            verdict=fit.verdict,
            fit_rows=[r.model_dump() for r in fit.rows],
            matched_skills=fit.matched_skills,
            gaps=fit.gaps,
            flags=fit.flags,
        )
    )
    await s.commit()


async def record_failure(s: AsyncSession, post: Post, error: str) -> None:
    attempts = post.attempts + 1
    fields = {"attempts": attempts, "skip_reason": f"error: {error}"[:500]}
    if attempts >= MAX_ATTEMPTS:
        fields["stage"] = "error"
    await update_post(s, post.id, **fields)
