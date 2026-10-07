"""Job cards (with live draft + send status), card buttons, scheduled/sent lists, Confirm/Dismiss of chat proposals."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_db
from app.chat import actions, tools
from app.db.models import Draft, Job, PendingAction, Post, Resume, Send, User
from app.llm import models
from app.mailer import drafts, outbox
from app.mailer.when import parse_when
from app.pipeline import graph, posts as post_info, report
from app.pipeline.sections import excerpt

router = APIRouter()


class DraftIn(BaseModel):
    model: str | None = None  # "Write emails with" picker; None = Auto


class DraftEdit(BaseModel):  # the pencil icon: the user's own words, sent as written
    subject: str = Field(max_length=300)
    body: str = Field(max_length=20_000)


class When(BaseModel):
    when: str = Field("now", max_length=60)
    to: list[str] | str | None = None  # which addresses (default: all of the post's, in one email)
    confirm: bool = False  # the user saw the warnings (recently emailed, already sent...) and sends anyway


def send_json(send: Send, job: Job | None = None) -> dict:
    out = {"id": send.id, "job_id": send.job_id, "to_email": send.to_email,
           "to_emails": send.to_emails or [send.to_email], "status": send.status,
           "send_at": send.send_at, "sent_at": send.sent_at, "replied_at": send.replied_at,
           "reply_snippet": send.reply_snippet, "test_mode": send.test_mode, "error": send.error, "subject": send.subject}
    if job is not None:
        out |= {"company": job.company, "role": job.role}
    return out


async def job_json(s: AsyncSession, job: Job) -> dict:
    post = await s.get(Post, job.post_id)
    draft = (await s.execute(select(Draft).where(Draft.job_id == job.id))).scalar_one_or_none()
    send = (await s.execute(select(Send).where(Send.job_id == job.id).order_by(Send.id.desc()).limit(1))).scalar_one_or_none()
    own_text = None
    if post:  # only this job's part of the post (a post can list many jobs)
        names = [(c, r) for c, r in (await s.execute(
            select(Job.company, Job.role).where(Job.post_id == post.id).order_by(Job.idx))).all()]
        own_text = excerpt(post.text, names, job.idx, job.hr_emails, job.apply_links)
    checked_with = await s.scalar(select(Resume.name).where(Resume.id == job.resume_id)) if job.resume_id else None
    return {
        "id": job.id, "company": job.company, "role": job.role, "location": job.location, "work_mode": job.work_mode,
        "experience": job.experience, "salary": job.salary, "fit_score": job.fit_score, "verdict": job.verdict,
        "must_have_skills": job.must_have_skills, "apply_instructions": job.apply_instructions, "hr_name": job.hr_name,
        "post_text": own_text, "checked_with": checked_with,
        "flags": job.flags, "fit_rows": job.fit_rows or [], "matched_skills": job.matched_skills, "gaps": job.gaps,
        "apply_method": job.apply_method, "hr_emails": job.hr_emails, "apply_links": job.apply_links,
        "posted_at": post.posted_at if post else None,
        "draft": None if draft is None else {
            "status": draft.status, "subject": draft.subject, "body": draft.body, "to_emails": draft.to_emails,
            "edited": draft.edited,
            "issues": draft.issues, "outdated": (why := await drafts.outdated_reason(s, draft)) is not None,
            "outdated_reason": why,
        },
        "send": None if send is None else send_json(send),
    }


async def _own_job(s: AsyncSession, user_id: uuid.UUID, job_id: int) -> Job:
    job = (await s.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "No such job")
    return job


@router.get("/jobs")
async def list_jobs(ids: str | None = None, date: str = "today", user: User = Depends(current_user),
                    s: AsyncSession = Depends(get_db)):
    """?ids=3,1,2 (chat cards, in that order) or ?date=today|yesterday|YYYY-MM-DD (Jobs screen, best first)."""
    if ids:
        wanted = [int(x) for x in ids.split(",") if x.strip().isdigit()][:100]
        rows = {j.id: j for j in (await s.execute(select(Job).where(Job.id.in_(wanted), Job.user_id == user.id))).scalars()}
        jobs = [rows[i] for i in wanted if i in rows]
    else:
        try:
            d = report.parse_day(date)
        except ValueError:
            raise HTTPException(400, "date must be today, yesterday or YYYY-MM-DD") from None
        jobs = [j for j, _ in (await report.day_report(s, user.id, d)).matches]
    return [await job_json(s, j) for j in jobs]


@router.get("/posts")
async def list_posts(ids: str | None = None, date: str = "today", user: User = Depends(current_user),
                     s: AsyncSession = Depends(get_db)):
    """'All posts': every Telegram post of a day (or ?ids= for chat cards), newest first, with a plain status and
    the same job cards as Recommended (so they can be selected, written and sent from here too)."""
    if ids:
        wanted = [int(x) for x in ids.split(",") if x.strip().isdigit()][:100]
        posts = await post_info.posts_by_ids(s, user.id, wanted)
    else:
        try:
            d = report.parse_day(date)
        except ValueError:
            raise HTTPException(400, "date must be today, yesterday or YYYY-MM-DD") from None
        posts = await post_info.day_posts(s, user.id, d)
    job_ids = [i for p in posts for i in p["job_ids"]]
    jobs = {j.id: j for j in (await s.execute(select(Job).where(Job.id.in_(job_ids), Job.user_id == user.id))).scalars()}
    for p in posts:
        p["jobs"] = [await job_json(s, jobs[i]) for i in p["job_ids"] if i in jobs]
    return posts


class CheckIn(BaseModel):
    force: bool = False  # read a skipped post anyway (user wants to apply despite a weak resume match)


@router.post("/posts/{post_id}/check")
async def check_post(post_id: int, body: CheckIn | None = None, user: User = Depends(current_user),
                     s: AsyncSession = Depends(get_db)):
    """'Check now' / 'Check again' on one post: run the AI on it now (a failed post starts over).
    force: past the resume-match gate straight to reading the job + fit check, like a pasted job."""
    post = (await s.execute(select(Post).where(Post.id == post_id, Post.user_id == user.id))).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "No such post")
    if body and body.force and post.stage in ("skipped", "error", "new"):
        post.stage, post.attempts, post.skip_reason = "matched", 0, None
        await s.commit()
    elif post.stage == "error":
        post.stage, post.attempts, post.skip_reason = "new", 0, None
        await s.commit()
    stage = await graph.run_post(tools._sessionmaker(s), post_id)
    if stage == "rate_limited":
        raise HTTPException(429, "The free AI is busy right now. Try again in a minute.")
    if stage == "unreachable":
        raise HTTPException(503, "Can't reach the AI right now. Check the internet, then try again.")
    if stage == "busy":
        raise HTTPException(409, "Already being checked. Refresh in a moment.")
    await s.refresh(post)  # the pipeline changed it in its own session
    return (await list_posts(ids=str(post_id), user=user, s=s))[0]


class FetchIn(BaseModel):
    date: str = Field("today", max_length=20)


@router.post("/jobs/fetch")
async def fetch(body: FetchIn, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """Jobs screen 'Fetch': read Telegram posts not saved yet and check posts not processed yet (no tokens wasted)."""
    now = datetime.now(UTC)
    try:
        d = report.parse_day(body.date, now.astimezone(report.IST).date())
    except ValueError:
        raise HTTPException(400, "date must be today, yesterday or YYYY-MM-DD") from None
    f = await tools.fetch_day(s, user.id, now, d)
    return {"new_posts": f.new_posts, "checked": f.checked, "waiting": f.waiting, "paused": f.paused, "problem": f.problem}


@router.post("/posts/check-day")
async def check_day(body: FetchIn, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """Opening a day in Jobs checks its waiting posts by itself (no 'Check now' button), same budget as Fetch."""
    now = datetime.now(UTC)
    try:
        d = report.parse_day(body.date, now.astimezone(report.IST).date())
    except ValueError:
        raise HTTPException(400, "date must be today, yesterday or YYYY-MM-DD") from None
    f = await tools.check_day(s, user.id, now, d)
    return {"checked": f.checked, "waiting": f.waiting, "paused": f.paused}


NOTIFY = ("TOP PRIORITY", "STRONG MATCH", "APPLY")  # worth telling the user about


@router.get("/jobs/new")
async def new_jobs(since: datetime, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """Good jobs found since the app last looked, the 'new jobs' badge (phone notifications come with the APK)."""
    rows = (await s.execute(select(Job).where(Job.user_id == user.id, Job.verdict.in_(NOTIFY), Job.created_at > since)
                            .order_by(Job.fit_score.desc()).limit(50))).scalars().all()
    return {"count": len(rows), "jobs": [{"id": j.id, "company": j.company, "role": j.role, "fit_score": j.fit_score}
                                          for j in rows]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    return await job_json(s, await _own_job(s, user.id, job_id))


@router.post("/jobs/{job_id}/draft")
async def write_draft(job_id: int, body: DraftIn | None = None, user: User = Depends(current_user),
                      s: AsyncSession = Depends(get_db)):
    model = body.model if body else None
    if model and model not in models.available():
        raise HTTPException(400, "That AI model isn't available.")
    job = await _own_job(s, user.id, job_id)
    try:
        await drafts.write_draft(s, user.id, job.id, model=model)
    except drafts.NotAnEmailJob:
        raise HTTPException(400, "This job is applied to through a link or form, not by email.") from None
    except drafts.NoResume:
        raise HTTPException(400, "Add a resume first.") from None
    except drafts.ProfileIncomplete as e:
        raise HTTPException(400, f"Your profile is missing your {', '.join(e.missing)}. Add it, then try again.") from None
    await outbox.refresh_waiting(s, user.id, job.id)  # a scheduled copy goes out with the new text, same time
    return await job_json(s, job)


@router.put("/jobs/{job_id}/draft")
async def edit_draft(job_id: int, body: DraftEdit, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    job = await _own_job(s, user.id, job_id)
    try:
        await drafts.edit_draft(s, user.id, job.id, body.subject, body.body)
    except drafts.JobNotFound:
        raise HTTPException(404, "Write the email first.") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    await outbox.refresh_waiting(s, user.id, job.id)
    return await job_json(s, job)


@router.post("/jobs/{job_id}/schedule")
async def schedule(job_id: int, body: When, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """Card button (the app asks the user to confirm before calling this). 409 {"confirm": [reasons]}: tell the user
    why it may not be wise (e.g. address emailed 3 days ago) and call again with confirm=true if they still want it."""
    job = await _own_job(s, user.id, job_id)
    try:
        send = await outbox.approve(s, user.id, job.id, parse_when(body.when), to=body.to, confirm=body.confirm)
    except outbox.NeedsConfirm as e:
        raise HTTPException(409, {"confirm": e.warnings}) from None
    except (outbox.NotAllowed, ValueError) as e:
        raise HTTPException(400, str(e)) from None
    return send_json(send, job)


@router.get("/sends")
async def list_sends(status: str | None = None, q: str | None = None, user: User = Depends(current_user),
                     s: AsyncSession = Depends(get_db)):
    """?status= filter; ?q= search (company, role, subject, HR addresses; every word must match) over all history."""
    text = q
    q = select(Send, Job).join(Job, Send.job_id == Job.id).where(Send.user_id == user.id, Send.hidden.is_(False))
    if status:
        q = q.where(Send.status == status)
    haystack = func.concat_ws(" ", Job.company, Job.role, Send.subject, func.array_to_string(Send.to_emails, " "))
    for word in (text or "").split()[:8]:
        q = q.where(haystack.ilike(f"%{word}%"))
    order = Send.send_at if status == "scheduled" else Send.send_at.desc()
    return [send_json(send, job) for send, job in (await s.execute(q.order_by(order).limit(300))).tuples()]


async def _own_send(s: AsyncSession, user_id: uuid.UUID, send_id: int) -> Send:
    send = (await s.execute(select(Send).where(Send.id == send_id, Send.user_id == user_id))).scalar_one_or_none()
    if send is None:
        raise HTTPException(404, "No such email")
    return send


@router.post("/sends/{send_id}/cancel")
async def cancel_send(send_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    send = await _own_send(s, user.id, send_id)
    try:
        await outbox.cancel(s, user.id, send.id)
    except outbox.NotAllowed as e:
        raise HTTPException(400, str(e)) from None
    return send_json(send)


@router.delete("/sends/{send_id}")
async def delete_send(send_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """Remove from Scheduled / Sent (a waiting email is cancelled). It can't recall an email already delivered."""
    try:
        await outbox.hide(s, user.id, send_id)
    except outbox.NotAllowed as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True}


@router.post("/sends/{send_id}/reschedule")
async def reschedule_send(send_id: int, body: When, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    send = await _own_send(s, user.id, send_id)
    try:
        send = await outbox.reschedule(s, user.id, send.id, parse_when(body.when))
    except (outbox.NotAllowed, ValueError) as e:
        raise HTTPException(400, str(e)) from None
    return send_json(send)


def action_json(a: PendingAction) -> dict:
    return {"id": a.id, "kind": a.kind, "summary": a.summary, "status": a.status, "result": a.result}


@router.get("/actions/{action_id}")
async def get_action(action_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    a = (await s.execute(select(PendingAction).where(PendingAction.id == action_id, PendingAction.user_id == user.id))
         ).scalar_one_or_none()
    if a is None:
        raise HTTPException(404, "No such action")
    return action_json(a)


async def _act(fn, s: AsyncSession, user_id: uuid.UUID, action_id: int, **kw) -> dict:
    try:
        return action_json(await fn(s, user_id, action_id, **kw))
    except actions.ActionError as e:
        raise HTTPException(404 if "No such" in str(e) else 409, str(e)) from None


@router.post("/actions/{action_id}/confirm")
async def confirm_action(action_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    return await _act(actions.confirm, s, user.id, action_id, now=datetime.now().astimezone())


@router.post("/actions/{action_id}/dismiss")
async def dismiss_action(action_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    return await _act(actions.dismiss, s, user.id, action_id)
