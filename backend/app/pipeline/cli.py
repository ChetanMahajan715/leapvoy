"""Pipeline CLI (app screens replace this in Steps 7–8).

  python -m app.pipeline.cli profile-seed --email me@x.com --file ../docs/templates/profile.seed.json
  python -m app.pipeline.cli resume-add   --email me@x.com --file ../private/resume.pdf --name "AI Engineer"
  python -m app.pipeline.cli run          --email me@x.com --limit 20
  python -m app.pipeline.cli jobs         --email me@x.com [--min-score 55]
  python -m app.pipeline.cli day          --email me@x.com [--date 2026-09-29] [--no-fetch]
"""

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.accounts.profile import get_profile, set_profile
from app.db.models import Job
from app.db.session import get_sessionmaker
from app.pipeline import graph, report
from app.pipeline.prefilter import find_emails, find_links
from app.pipeline.resume import active_resume, add_resume, link_mismatches, pdf_links
from app.telegram import reader
from app.telegram import store as tstore
from app.telegram.store import get_or_create_user


def apply_to(job: Job) -> str:
    """Where to apply: HR email(s), or the apply link for form/portal jobs."""
    if job.apply_method == "email":
        return "[mail] " + ", ".join(job.hr_emails)
    return "[link] " + " ".join(job.apply_links)


def read_seed(path: Path) -> dict:
    """Seed file keys starting with "_" are notes, not profile values."""
    return {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if not k.startswith("_")}


async def _user(email: str):
    async with get_sessionmaker()() as s:
        return await get_or_create_user(s, email)


async def profile_seed(email: str, file: Path) -> None:
    user_id = await _user(email)
    async with get_sessionmaker()() as s:
        await set_profile(s, user_id, read_seed(file))
    print(f"OK: profile saved for {email}")


async def resume_add(email: str, file: Path, name: str) -> None:
    user_id = await _user(email)
    pdf = file.read_bytes()
    async with get_sessionmaker()() as s:
        r = await add_resume(s, user_id, name, pdf, filename=file.name)
        warnings = link_mismatches(pdf_links(pdf), await get_profile(s, user_id))
    print(f"OK: resume '{r.name}' is now active ({len(r.text)} characters). Older versions are kept.")
    for w in warnings:
        print(f"WARNING: {w}")


async def run(email: str, limit: int) -> None:
    counts = await graph.run_user(get_sessionmaker(), await _user(email), limit)
    print("Result:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nothing to do")


async def jobs(email: str, min_score: int, limit: int) -> None:
    user_id = await _user(email)
    async with get_sessionmaker()() as s:
        rows = (
            await s.execute(
                select(Job)
                .where(Job.user_id == user_id, Job.fit_score >= min_score)
                .order_by(Job.fit_score.desc(), Job.id.desc())
                .limit(limit)
            )
        ).scalars().all()
    for j in rows:
        flags = f"  [{'; '.join(j.flags)}]" if j.flags else ""
        print(f"#{j.id:<5} {j.fit_score:>3}  {j.verdict:<12}  {j.company} · {j.role}  → {apply_to(j)}{flags}")
    print(f"\n{len(rows)} job(s) with score ≥ {min_score}")


async def day(email: str, d: date, fetch: bool) -> None:
    sm = get_sessionmaker()
    user_id = await _user(email)
    if fetch:  # pull anything Telegram has that we don't, right now
        async with sm() as s:
            session_str = await tstore.load_session(s, user_id)
        if session_str:
            client = await reader.connect(session_str)
            try:
                new = await reader.catch_up(client, sm, user_id)
            finally:
                await client.disconnect()
            print(f"Fetched {new} new post(s) from Telegram.")
        await graph.run_user(sm, user_id, 500, *report.day_bounds(d))  # only this day's posts
    async with sm() as s:
        r = await report.day_report(s, user_id, d)
        has_resume = await active_resume(s, user_id) is not None

    print(f"\n=== {d:%d %b %Y} (India time) · ALL POSTS: {len(r.posts)} ===")
    for p in r.posts:
        tag = p.stage if p.stage != "skipped" else f"skip:{p.skip_reason}"
        how = "[mail]" if find_emails(p.text) else "[link]" if find_links(p.text) else "[ -- ]"
        print(f"{p.posted_at.astimezone(report.IST):%H:%M}  {how} {tag:<22} {' '.join(p.text.split())[:85]}")
    print(f"\n=== JOBS FOR YOUR RESUME: {len(r.matches)} ===")
    for j, p in r.matches:
        flags = f"  [{'; '.join(j.flags)}]" if j.flags else ""
        print(f"#{j.id:<5} {j.fit_score:>3}  {j.verdict:<12}  {j.company} · {j.role}  → {apply_to(j)}{flags}")
    if not has_resume:
        print("(No resume yet → add one with resume-add; posts wait until then.)")
    if r.pending:
        print(f"\nStill processing: {r.pending} post(s).")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.pipeline.cli", description="Leapvoy AI pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, help_ in [
        ("profile-seed", "load profile values (city, education, links) from a JSON file"),
        ("resume-add", "add a resume PDF; it becomes the active one"),
        ("run", "process pending posts now"),
        ("jobs", "list scored jobs, best first"),
        ("day", "all posts of a day + the jobs that fit your resume (fetches fresh from Telegram first)"),
    ]:
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--email", required=True)
        if name in ("profile-seed", "resume-add"):
            sp.add_argument("--file", required=True, type=Path)
        if name == "resume-add":
            sp.add_argument("--name", default="Resume")
        if name == "run":
            sp.add_argument("--limit", type=int, default=20)
        if name == "jobs":
            sp.add_argument("--min-score", type=int, default=0)
            sp.add_argument("--limit", type=int, default=30)
        if name == "day":
            sp.add_argument("--date", type=report.parse_day, default="today", help="today | yesterday | YYYY-MM-DD (IST)")
            sp.add_argument("--no-fetch", action="store_true", help="skip the live Telegram fetch")
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    job = {
        "profile-seed": lambda: profile_seed(a.email, a.file),
        "resume-add": lambda: resume_add(a.email, a.file, a.name),
        "run": lambda: run(a.email, a.limit),
        "jobs": lambda: jobs(a.email, a.min_score, a.limit),
        "day": lambda: day(a.email, a.date, not a.no_fetch),
    }[a.cmd]
    asyncio.run(job())


if __name__ == "__main__":
    main()
