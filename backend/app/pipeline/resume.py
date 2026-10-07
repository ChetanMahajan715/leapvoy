"""Resume PDF → text → chunks → pgvector; match a post against the user's active resume."""

import asyncio
from datetime import timedelta
import re
import uuid

import pymupdf
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Draft, Job, Post, Resume, ResumeChunk, Send
from app.pipeline import embed
from app.pipeline.report import day_bounds, today

MIN_TEXT = 200  # fewer characters → probably a scanned image PDF


class ScannedPdfError(ValueError):
    """PDF has (almost) no text layer, and OCR couldn't read it either."""


class ResumeNotFound(LookupError):
    pass


class ActiveResume(ValueError):
    """The active resume is used for matching; make another one active first."""


class ResumeInUse(ValueError):
    """A scheduled email will attach this version's PDF."""


def pdf_to_text(pdf: bytes) -> str:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        text = "\n".join(page.get_text() for page in doc).strip()
    if len(text) < MIN_TEXT:
        raise ScannedPdfError("No readable text in this PDF (scanned image?). Upload a text PDF.")
    return text


def pdf_or_ocr_text(pdf: bytes) -> str:
    """Text layer; a scanned resume (picture only) is read with the same on-server OCR as chat attachments.
    Blocking (CPU): call it in a thread from request handlers."""
    try:
        return pdf_to_text(pdf)
    except ScannedPdfError:
        from app.chat import files  # OCR models load only when needed

        try:
            text = files.read_file("resume.pdf", pdf).strip()
        except files.Unsupported:
            text = ""
        if len(text) < MIN_TEXT:
            raise ScannedPdfError("Couldn't read this PDF, even with OCR. Upload a clearer scan or a text PDF.") from None
        return text


def pdf_links(pdf: bytes) -> list[str]:
    """Clickable links in the PDF (icons like GitHub/LinkedIn/email hide their URL here, not in the text)."""
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        uris = [link["uri"] for page in doc for link in page.get_links() if link.get("uri")]
    return list(dict.fromkeys(uris))


def _handle(url: str, marker: str) -> str | None:
    """'https://www.linkedin.com/in/Abc/' + '/in/' → 'abc'."""
    m = re.search(re.escape(marker) + r"([^/?#]+)", url, re.I)
    return m.group(1).lower() if m else None


def link_mismatches(links: list[str], profile: dict) -> list[str]:
    """Warnings when the resume's GitHub / LinkedIn / email differ from the profile used in emails."""
    warnings = []
    for name, marker, key in (("GitHub", "github.com/", "github_url"), ("LinkedIn", "linkedin.com/in/", "linkedin_url")):
        want = _handle(profile.get(key) or "", marker)
        for url in links:
            have = _handle(url, marker)
            if want and have and have != want:
                warnings.append(f"Resume {name} is {marker}{have} but your profile uses {profile[key].split('//')[-1]}")
    sender = (profile.get("sender_email") or "").lower()
    for url in links:
        if url.lower().startswith("mailto:") and sender and url[7:].split("?")[0].lower() != sender:
            warnings.append(f"Resume email is {url[7:]} but you send from {sender}")
    return list(dict.fromkeys(warnings))  # repo links under the same account → one warning


def chunk(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    """Word-boundary windows of ≤ size chars, each starting ~overlap chars before the previous end."""
    words, chunks, current = text.split(), [], []
    for word in words:
        if current and len(" ".join([*current, word])) > size:
            chunks.append(" ".join(current))
            tail: list[str] = []
            while current and len(" ".join([current[-1], *tail])) <= overlap:
                tail.insert(0, current.pop())
            current = tail
        current.append(word)
    if current:
        chunks.append(" ".join(current))
    return chunks


async def _embed(texts: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(embed.embed, texts)  # CPU work off the event loop


async def add_resume(
    s: AsyncSession, user_id: uuid.UUID, name: str, pdf: bytes, filename: str = "resume.pdf", text: str | None = None,
    primary: bool = True,
) -> Resume:
    """primary: the new version becomes the one used for matching and emails (the first resume always does);
    otherwise it is just stored. Older versions stay (switch later). The PDF is kept for attaching.
    text: already read (e.g. OCR'd in a thread by the API); else read here."""
    text = text or pdf_or_ocr_text(pdf)
    pieces = chunk(text)
    vectors = await _embed(pieces)
    primary = primary or await active_resume(s, user_id) is None
    if primary:
        await s.execute(update(Resume).where(Resume.user_id == user_id).values(is_active=False))
    r = Resume(user_id=user_id, name=name, text=text, pdf=pdf, filename=filename, is_active=primary)
    s.add(r)
    await s.flush()
    s.add_all(
        ResumeChunk(
            user_id=user_id, resume_id=r.id, idx=i, text=t, embedding=v, embed_model=embed.MODEL, embed_lib=embed.LIB
        )
        for i, (t, v) in enumerate(zip(pieces, vectors, strict=True))
    )
    await s.commit()
    return r


async def active_resume(s: AsyncSession, user_id: uuid.UUID) -> Resume | None:
    return (
        await s.execute(select(Resume).where(Resume.user_id == user_id, Resume.is_active))
    ).scalar_one_or_none()


async def _own(s: AsyncSession, user_id: uuid.UUID, resume_id: int) -> Resume:
    r = (await s.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))).scalar_one_or_none()
    if r is None:
        raise ResumeNotFound(resume_id)
    return r


async def list_resumes(s: AsyncSession, user_id: uuid.UUID) -> list[tuple[Resume, int]]:
    """Newest first, each with how many email drafts were written from it."""
    drafts = select(func.count()).select_from(Draft).where(Draft.resume_id == Resume.id).scalar_subquery()
    rows = await s.execute(
        select(Resume, drafts).where(Resume.user_id == user_id).order_by(Resume.created_at.desc(), Resume.id.desc())
    )
    return [(r, n) for r, n in rows.all()]


async def activate_resume(s: AsyncSession, user_id: uuid.UUID, resume_id: int) -> Resume:
    """Switch back to an older version (its vectors were kept)."""
    r = await _own(s, user_id, resume_id)
    await s.execute(update(Resume).where(Resume.user_id == user_id).values(is_active=False))
    r.is_active = True
    await s.commit()
    return r


async def recheck_recent(s: AsyncSession, user_id: uuid.UUID) -> int:
    """After the primary resume changes: today's and yesterday's (India) jobs are scored again with it, and posts
    skipped as a weak match get a second look. Jobs already emailed keep their score. Returns posts queued."""
    since, _ = day_bounds(today() - timedelta(days=1))
    recent = select(Post.id).where(Post.user_id == user_id, Post.posted_at >= since)
    emailed = select(Send.job_id).where(Send.user_id == user_id)
    jobs = select(Job.id).where(Job.user_id == user_id, Job.post_id.in_(recent), Job.id.not_in(emailed))
    cleared = (await s.execute(update(Job).where(Job.id.in_(jobs)).values(
        fit_score=None, verdict=None, fit_rows=None, matched_skills=[], gaps=[], flags=[], resume_id=None,
    ).returning(Job.post_id))).scalars().all()
    rescore = (await s.execute(update(Post).where(Post.id.in_(set(cleared)), Post.stage == "scored")
                               .values(stage="extracted").returning(Post.id))).scalars().all()
    rematch = (await s.execute(update(Post).where(
        Post.id.in_(recent), Post.stage == "skipped", Post.skip_reason == "low_match"
    ).values(stage="new", skip_reason=None).returning(Post.id))).scalars().all()
    await s.commit()
    return len(rescore) + len(rematch)


async def delete_resume(s: AsyncSession, user_id: uuid.UUID, resume_id: int) -> None:
    """Drafts written from it go too (they were outdated); sent emails keep their own copy."""
    r = await _own(s, user_id, resume_id)
    if r.is_active:
        raise ActiveResume(resume_id)
    waiting = await s.scalar(select(func.count()).select_from(Send).join(Draft, Send.draft_id == Draft.id).where(
        Draft.resume_id == r.id, Send.status.in_(("scheduled", "sending"))))
    if waiting:
        raise ResumeInUse(resume_id)  # it would go out without the resume attached
    await s.execute(delete(ResumeChunk).where(ResumeChunk.resume_id == r.id))
    await s.delete(r)
    await s.commit()


async def _reembed_stale(s: AsyncSession, resume_id: int) -> None:
    stale = (
        await s.execute(
            select(ResumeChunk).where(
                ResumeChunk.resume_id == resume_id,
                (ResumeChunk.embed_model != embed.MODEL) | (ResumeChunk.embed_lib != embed.LIB),
            )
        )
    ).scalars().all()
    if not stale:
        return
    for c, v in zip(stale, await _embed([c.text for c in stale]), strict=True):
        c.embedding, c.embed_model, c.embed_lib = v, embed.MODEL, embed.LIB
    await s.commit()


async def match_score(s: AsyncSession, user_id: uuid.UUID, text: str | list[str]) -> float | None:
    """Best cosine similarity between the post (or any of its texts, e.g. one per job in a multi-job post) and any
    chunk of the active resume. None = no resume yet."""
    r = await active_resume(s, user_id)
    if r is None:
        return None
    await _reembed_stale(s, r.id)
    best = 0.0
    for v in await _embed([text] if isinstance(text, str) else text):
        distance = (
            await s.execute(
                select(func.min(ResumeChunk.embedding.cosine_distance(v))).where(
                    ResumeChunk.user_id == user_id, ResumeChunk.resume_id == r.id
                )
            )
        ).scalar_one()
        best = max(best, 1 - distance)
    return best
