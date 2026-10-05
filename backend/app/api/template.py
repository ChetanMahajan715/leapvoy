"""Template preview: the real approved template, rendered with the user's profile and a job, split into labelled parts
(fixed text · from your profile · from the job · written by the AI) so the app can colour them."""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.profile import get_profile
from app.api.deps import current_user, get_db
from app.db.models import Job, Post, User
from app.mailer import templates
from app.mailer.render import render
from app.mailer.rules import hr_first_name, subject_parts

router = APIRouter()
_PART = re.compile(r"\x01([pja])(.*?)\x02", re.S)
KINDS = {"p": "profile", "j": "job", "a": "ai"}
PROFILE = {"full_name": "full name", "phone": "phone", "linkedin_url": "LinkedIn link", "github_url": "GitHub link"}


def _mark(kind: str, text: str) -> str:
    return f"\x01{kind}{text}\x02"


def split(text: str) -> list[dict]:
    """'Dear \x01jAditi\x02,' → [{fixed 'Dear '}, {job 'Aditi'}, {fixed ','}] (neighbours of one kind merged)."""
    parts: list[dict] = []
    pos = 0
    for m in _PART.finditer(text):
        for kind, piece in (("fixed", text[pos:m.start()]), (KINDS[m.group(1)], m.group(2))):
            if not piece:
                continue
            if parts and parts[-1]["kind"] == kind:
                parts[-1]["text"] += piece
            else:
                parts.append({"kind": kind, "text": piece})
        pos = m.end()
    if text[pos:]:
        parts.append({"kind": "fixed", "text": text[pos:]})
    return parts


async def _parts(s: AsyncSession, user_id, jinja: str, job_id: int | None) -> dict:
    profile = await get_profile(s, user_id)
    role, company, hr, override, extras, job_json = "AI Engineer", "Acme Technologies", None, None, "", None
    if job_id is not None:
        job = (await s.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "No such job")
        post = await s.get(Post, job.post_id)
        role, company, hr = job.role, job.company.strip().strip("."), hr_first_name(job.hr_name)
        override, extras = subject_parts(job, profile, post.text if post else "")
        job_json = {"id": job.id, "company": job.company, "role": job.role}
    values = {
        "role": _mark("j", role), "company": _mark("j", company), "hr_first_name": _mark("j", hr) if hr else None,
        "subject_override": _mark("j", override) if override else None,
        "subject_extras": _mark("j", extras) if extras else "",
        "profile": {k: _mark("p", profile.get(k) or f"(add your {label} in Profile)") for k, label in PROFILE.items()},
        "opening_line": _mark("a", "[AI: one or two sentences on why this role fits you, from your resume]"),
        "fit_bullets": [{"label": _mark("a", "[AI: skill area]"), "proof": _mark("a", f"[AI: proof {i} from your resume]")}
                        for i in (1, 2, 3)],
        "closing_line": _mark("a", "[AI: a closing line on availability and location, from your profile]"),
    }
    subject, body = render(jinja, **values)
    return {"job": job_json, "subject": split(subject), "body": split(body)}


@router.get("/template")
async def preview(job_id: int | None = None, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """The active template (the user's own version, or the approved default), filled in."""
    tpl = await templates.active(s, user.id)
    return {"name": tpl.name, **await _parts(s, user.id, tpl.jinja, job_id)}


async def editor_json(s: AsyncSession, user_id) -> dict:
    tpl = await templates.active(s, user_id)
    return {
        "active": tpl.name, "text": tpl.text, "default_text": templates.DEFAULT_TEXT,
        "tags": [{"tag": f"{{{k}}}", "means": v[0], "ai": k in templates.AI_TAGS} for k, v in templates.TAGS.items()],
        "versions": [{"id": v.id, "version": v.version, "created_at": v.created_at, "is_active": v.is_active}
                     for v in await templates.versions(s, user_id)],
    }


@router.get("/templates")
async def editor(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    return await editor_json(s, user.id)


class TemplateIn(BaseModel):
    text: str = Field(max_length=templates.MAX_CHARS + 100)
    job_id: int | None = None


@router.post("/templates/preview")
async def try_text(body: TemplateIn, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """Live preview while editing; nothing is saved."""
    try:
        jinja = templates.to_jinja(body.text)
    except templates.TemplateError as e:
        raise HTTPException(422, str(e)) from None
    return await _parts(s, user.id, jinja, body.job_id)


@router.post("/templates")
async def save(body: TemplateIn, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """New version, used from now on. Emails already written get 'Rewrite email'."""
    try:
        await templates.save(s, user.id, body.text)
    except templates.TemplateError as e:
        raise HTTPException(422, str(e)) from None
    return await editor_json(s, user.id)


@router.post("/templates/default")
async def back_to_default(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    await templates.use_default(s, user.id)
    return await editor_json(s, user.id)


@router.post("/templates/{template_id}/activate")
async def use_version(template_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    try:
        await templates.activate(s, user.id, template_id)
    except templates.TemplateNotFound:
        raise HTTPException(404, "No such template version") from None
    return await editor_json(s, user.id)
