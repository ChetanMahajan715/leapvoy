"""Settings: the profile every email ends with, and resume versions (upload / switch back / delete)."""

import base64
import binascii
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.accounts.profile import get_profile, set_profile
from app.api.deps import current_user, get_db
from app.db.models import Draft, Resume, User
from app.pipeline import resume as resumes

router = APIRouter()
FIELDS = ("full_name", "phone", "linkedin_url", "github_url", "sender_email", "education", "home_city", "availability")
MAX_PDF = 5 * 1024 * 1024


class ProfileIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=80)
    phone: str = Field(max_length=20)
    linkedin_url: str = Field(max_length=200)
    github_url: str = Field(max_length=200)
    sender_email: EmailStr | None = None
    education: str = Field("", max_length=200)
    home_city: str = Field("", max_length=80)
    availability: str = Field("", max_length=200)

    @field_validator("full_name", "education", "home_city", "availability")
    @classmethod
    def _trim(cls, v: str) -> str:
        return v.strip()

    @field_validator("sender_email", mode="before")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        return v.strip() or None if isinstance(v, str) else v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        if len(re.sub(r"\D", "", v)) < 10:
            raise ValueError("Enter a phone number with at least 10 digits.")
        return v.strip()

    @field_validator("linkedin_url")
    @classmethod
    def _linkedin(cls, v: str) -> str:
        if not re.search(r"linkedin\.com/in/[^/\s]+", v, re.I):
            raise ValueError("Use your LinkedIn profile link, like https://linkedin.com/in/your-name")
        return v.strip()

    @field_validator("github_url")
    @classmethod
    def _github(cls, v: str) -> str:
        if not re.search(r"github\.com/[^/\s]+", v, re.I):
            raise ValueError("Use your GitHub link, like https://github.com/your-name")
        return v.strip()


@router.get("/profile")
async def read_profile(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    p = await get_profile(s, user.id)
    return {k: str(p.get(k) or "") for k in FIELDS}


@router.put("/profile")
async def save_profile(body: ProfileIn, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    current = await get_profile(s, user.id)  # keeps keys the app doesn't edit (target_roles, _note)
    await set_profile(s, user.id, {**current, **{k: v or "" for k, v in body.model_dump().items()}})
    return await read_profile(user, s)


def resume_json(r: Resume, drafts: int = 0) -> dict:
    return {"id": r.id, "name": r.name, "filename": r.filename, "is_active": r.is_active, "created_at": r.created_at,
            "chars": len(r.text), "drafts": drafts}


async def _outdated(s: AsyncSession, user_id: uuid.UUID, active_id: int) -> int:
    """Drafts written from another version: they now show 'Rewrite email'."""
    return await s.scalar(
        select(func.count()).select_from(Draft).where(Draft.user_id == user_id, Draft.resume_id != active_id)
    )


@router.get("/resumes")
async def list_resumes(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    return [resume_json(r, n) for r, n in await resumes.list_resumes(s, user.id)]


class ResumeIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    filename: str = Field(min_length=1, max_length=255)
    data: str = Field(max_length=MAX_PDF * 4 // 3 + 8)  # base64 JSON: Expo's native fetch can't post {uri} FormData
    primary: bool = True  # use it for matching and emails from now on (the first resume always is)


@router.post("/resumes")
async def upload_resume(body: ResumeIn, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """Stores a new version, primary if asked (then recent jobs are re-checked with it). Scanned PDFs are OCR'd.
    Says which links differ from the profile."""
    if not body.filename.lower().endswith(".pdf"):
        raise HTTPException(415, "Upload your resume as a PDF.")
    try:
        pdf = base64.b64decode(body.data, validate=True)
    except binascii.Error:
        raise HTTPException(400, "The file didn't arrive correctly. Try again.") from None
    if len(pdf) > MAX_PDF:
        raise HTTPException(413, "That PDF is bigger than 5 MB.")
    if not pdf.startswith(b"%PDF"):
        raise HTTPException(415, "That file isn't a PDF.")
    try:
        text = await run_in_threadpool(resumes.pdf_or_ocr_text, pdf)  # OCR is CPU work: off the event loop
    except resumes.ScannedPdfError as e:
        raise HTTPException(422, str(e)) from None
    r = await resumes.add_resume(s, user.id, body.name.strip(), pdf, filename=body.filename, text=text,
                                 primary=body.primary)
    rechecking = await resumes.recheck_recent(s, user.id) if r.is_active else 0
    warnings = resumes.link_mismatches(resumes.pdf_links(pdf), await get_profile(s, user.id))
    active = await resumes.active_resume(s, user.id)
    return {"resume": resume_json(r), "warnings": warnings, "rechecking": rechecking,
            "outdated_drafts": await _outdated(s, user.id, active.id)}


@router.post("/resumes/{resume_id}/activate")
async def activate(resume_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    """Make this the primary resume; today's and yesterday's jobs are re-checked with it."""
    current = await resumes.active_resume(s, user.id)
    try:
        r = await resumes.activate_resume(s, user.id, resume_id)
    except resumes.ResumeNotFound:
        raise HTTPException(404, "No such resume") from None
    rechecking = 0 if current and current.id == r.id else await resumes.recheck_recent(s, user.id)
    return {**resume_json(r), "rechecking": rechecking, "outdated_drafts": await _outdated(s, user.id, r.id)}


@router.delete("/resumes/{resume_id}")
async def remove(resume_id: int, user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    try:
        await resumes.delete_resume(s, user.id, resume_id)
    except resumes.ResumeNotFound:
        raise HTTPException(404, "No such resume") from None
    except resumes.ActiveResume:
        raise HTTPException(409, "This is your primary resume. Make another one primary first.") from None
    except resumes.ResumeInUse:
        raise HTTPException(409, "A scheduled email will attach this resume. Cancel it or let it send first.") from None
    return Response(status_code=204)
