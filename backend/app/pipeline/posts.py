"""Every Telegram post, described in plain words for the 'All posts' tab and chat: Telegram's time, company, role,
and what happened to it (a fit, or why not). Also the professional names for verdicts."""

import re
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Job, Post
from app.pipeline import report

LABELS = {"TOP PRIORITY": "Excellent fit", "STRONG MATCH": "Strong fit", "APPLY": "Good fit", "MAYBE": "Possible fit",
          "SKIP": "Not a fit"}
_TITLE = re.compile(r"Company\s*[-:–]\s*(.+?)\s+Role\s*[-:–]\s*(.+?)(?=\s+(?:Batch|CTC|Salary|Stipend|Location|Experience"
                    r"|Job|Eligibility)\b|$)", re.I)
_LINE = {k: re.compile(rf"^\W*{k}(?:\s+name)?\s*[-:–]\s*(.+)$", re.I | re.M) for k in ("company", "role")}
_SKIPPED = {
    "no_apply_method": "No email or apply link found",
    "no_valid_job": "No email or apply link found",
    "duplicate": "Repost of an earlier post",
    "low_match": "Weak match with your resume",
}


def verdict_label(verdict: str | None) -> str | None:
    """'STRONG MATCH' → 'Strong fit' (what the user sees; the stored verdicts stay the same)."""
    return LABELS.get(verdict, verdict) if verdict else None


def post_title(text: str) -> str:
    """'Company: Role' from the post's own Company / Role lines, else its first line."""
    company = _LINE["company"].search(text)
    role = _LINE["role"].search(text)
    if company and role:
        return f"{company.group(1).strip()} · {role.group(1).strip()}"
    m = _TITLE.search(" ".join(text.split()))  # both on one line
    if m:
        return f"{m.group(1)} · {m.group(2)}"
    return next((line.strip() for line in text.splitlines() if line.strip()), "")[:80]


def _why_not(job: Job) -> str:
    if any(f.startswith("not a target role") for f in job.flags):
        return "not your target role"
    return job.flags[0] if job.flags else "not your target role"


def describe(post: Post, jobs: list[Job], channel: str) -> dict:
    """kind: fit (worth a look) · skipped (with the reason) · pending (AI not run yet) · failed (AI gave up)."""
    if post.stage == "skipped":
        kind, status = "skipped", _SKIPPED.get(post.skip_reason or "", f"Skipped: {post.skip_reason}")
    elif post.stage == "error":
        kind, status = "failed", "AI check failed. Try again"
    elif post.stage != "scored":
        kind, status = "pending", "Waiting for AI check"
    elif not jobs:
        kind, status = "skipped", "No job found in the post"
    else:
        good = sorted((j for j in jobs if j.verdict != "SKIP"), key=lambda j: -(j.fit_score or 0))
        if good:
            more = f" · {len(jobs)} jobs" if len(jobs) > 1 else ""
            kind, status = "fit", f"{verdict_label(good[0].verdict)} · {good[0].fit_score}/100{more}"
        else:
            kind, status = "skipped", f"Not a fit: {_why_not(jobs[0])}"
    return {"id": post.id, "tg_message_id": post.tg_message_id, "posted_at": post.posted_at, "channel": channel,
            "title": post_title(post.text), "text": post.text, "kind": kind, "status": status,
            "job_ids": [j.id for j in jobs], "has_email": bool(post.emails), "has_link": bool(post.links),
            "emails": post.emails, "links": post.links}


async def describe_all(s: AsyncSession, user_id: uuid.UUID, posts: list[Post]) -> list[dict]:
    ids = [p.id for p in posts]
    jobs: dict[int, list[Job]] = {}
    for j in (await s.execute(select(Job).where(Job.user_id == user_id, Job.post_id.in_(ids)).order_by(Job.idx))).scalars():
        jobs.setdefault(j.post_id, []).append(j)
    channels = dict((await s.execute(select(Channel.id, Channel.title).where(Channel.user_id == user_id))).all())
    return [describe(p, jobs.get(p.id, []), channels.get(p.channel_id, "")) for p in posts]


async def day_posts(s: AsyncSession, user_id: uuid.UUID, d: date) -> list[dict]:
    """Every saved post of that India day, newest first (Telegram's own posting time)."""
    start, end = report.day_bounds(d)
    posts = (await s.execute(select(Post).where(Post.user_id == user_id, Post.posted_at >= start, Post.posted_at < end)
                             .order_by(Post.posted_at.desc(), Post.tg_message_id.desc()))).scalars().all()
    return await describe_all(s, user_id, list(posts))


async def posts_by_ids(s: AsyncSession, user_id: uuid.UUID, ids: list[int]) -> list[dict]:
    posts = (await s.execute(select(Post).where(Post.user_id == user_id, Post.id.in_(ids))
                             .order_by(Post.posted_at.desc(), Post.tg_message_id.desc()))).scalars().all()
    return await describe_all(s, user_id, list(posts))


def ist_time(p: dict) -> str:
    return f"{p['posted_at'].astimezone(report.IST):%I:%M %p}".lstrip("0")
