"""Write the application email for one job: approved template + 3 AI-written parts from the ACTIVE resume.

Every draft is checked (fake skills, length, plain text). A failed check sends the AI a correction and it
rewrites (max MAX_ATTEMPTS); if it still fails the draft is saved as needs_review with the reasons.
Nothing is sent here: sending needs the user's approval (Step 5).
"""

import json
import re
import uuid
from datetime import datetime
from functools import cache

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.profile import get_profile
from app.db.models import Draft, Job, Post
from app.llm import prompts
from app.llm.router import structured
from app.llm.schemas import EmailSlots
from app.mailer import examples, templates
from app.mailer.guard import unsupported_claims
from app.mailer.render import MAX_WORDS, MIN_WORDS, default_template, render, word_count
from app.mailer.rules import hr_first_name, location_phrase, subject_parts
from app.pipeline.resume import active_resume

MAX_ATTEMPTS = 3
TEMPLATE_NAME = "default-v1"
NOT_PLAIN = re.compile(r"\*\*|__|[\U0001F300-\U0001FAFF☀-➿]")


class JobNotFound(LookupError):
    pass


class NotAnEmailJob(ValueError):
    """Link / Google-Form jobs are applied to on the website, not by email."""


class NoResume(RuntimeError):
    pass


NEEDED = {"full_name": "full name", "phone": "phone number", "linkedin_url": "LinkedIn link", "github_url": "GitHub link"}


class ProfileIncomplete(ValueError):
    """The approved template signs off with these; checked before any AI call."""

    def __init__(self, missing: list[str]):
        super().__init__(", ".join(missing))
        self.missing = missing


@cache
def style_examples(resume_text: str) -> str:
    """The approved sample emails as style guidance, minus any bullet the CURRENT resume doesn't back,
    so the AI can't copy old facts (e.g. a project that is no longer on the resume)."""
    parts = []
    for email in examples.load():
        s = examples.slots_from(email)
        backed = [b for b in s["fit_bullets"] if not unsupported_claims([b], "", resume_text)]
        bullets = "\n".join(f"- {b['label']}: {b['proof']}" for b in backed)
        parts.append(f"[{s['role']} at {s['company']}]\nopening_line: {s['opening_line']}\n"
                     f"fit_bullets:\n{bullets}\nclosing_line: {s['closing_line']}")
    return "\n\n".join(parts)


_PLAIN = str.maketrans({"‐": "-", "‑": "-", " ": " ", " ": " ", " ": " ", "​": ""})


EM_DASH = chr(0x2014)


def plain(slots: EmailSlots) -> EmailSlots:
    """Non-breaking hyphens/spaces from the AI → normal characters (they show as odd symbols in some mail apps).
    The em dash is never used (user's rule): " X " becomes ", ", a joined one a hyphen."""
    text = slots.model_dump_json().replace(f" {EM_DASH} ", ", ").replace(EM_DASH, "-")
    return EmailSlots.model_validate_json(text.translate(_PLAIN))


def _problems(slots: EmailSlots, body: str, resume_text: str, profile: dict,
              bounds: tuple[int, int] = (MIN_WORDS, MAX_WORDS)) -> list[str]:
    bullets = [b.model_dump() for b in slots.fit_bullets]
    profile_text = " ".join(str(v) for v in profile.values())
    problems = []
    if claims := unsupported_claims(bullets, slots.closing_line, resume_text, profile_text, slots.opening_line):
        problems.append(f"These are not in your resume: {', '.join(claims)}. Remove them or use only resume facts.")
    lo, hi = bounds
    if not lo <= (n := word_count(body)) <= hi:
        problems.append(f"The email is {n} words; it must be {lo}–{hi} words.")
    if NOT_PLAIN.search(body):
        problems.append("Use plain text only: no bold, markdown or emojis.")
    return problems


async def write_draft(s: AsyncSession, user_id: uuid.UUID, job_id: int, model: str | None = None) -> Draft:
    """model: the user's pick for writing emails (None = Auto); other models stay as backup."""
    job = (await s.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))).scalar_one_or_none()
    if job is None:
        raise JobNotFound(job_id)
    if job.apply_method != "email" or not job.hr_emails:
        raise NotAnEmailJob(job_id)
    resume = await active_resume(s, user_id)
    if resume is None:
        raise NoResume
    post = await s.get(Post, job.post_id)
    profile = await get_profile(s, user_id)
    if missing := [label for key, label in NEEDED.items() if not profile.get(key)]:
        raise ProfileIncomplete(missing)

    override, extras = subject_parts(job, profile, post.text)
    fixed = {"role": job.role, "company": job.company, "hr_first_name": hr_first_name(job.hr_name),
             "subject_override": override, "subject_extras": extras, "profile": profile}
    facts = {
        "job": {k: getattr(job, k) for k in ("company", "role", "experience", "location", "work_mode",
                                             "must_have_skills", "apply_instructions")},
        "fit_check": job.fit_rows or [],
        "education": profile.get("education"),
        "availability": profile.get("availability"),
        "location_phrase": location_phrase(job, profile),
    }
    messages = [
        {"role": "system", "content": prompts.load("email").format(examples=style_examples(resume.text), resume=resume.text)},
        {"role": "user", "content": f"{json.dumps(facts, ensure_ascii=False)}\n\nOriginal job post:\n{post.text}"},
    ]
    tpl = await templates.active(s, user_id)
    bounds = word_bounds(tpl.jinja, fixed)
    for _ in range(MAX_ATTEMPTS):
        slots = plain(await structured("large", messages, EmailSlots, temperature=0.3, prefer=model))
        values = fixed | slots.model_dump()
        subject, body = render(tpl.jinja, **values)
        problems = _problems(slots, body, resume.text, profile, bounds)
        if not problems:
            break
        messages = [*messages, {"role": "assistant", "content": slots.model_dump_json()},
                    {"role": "user", "content": "Rewrite the three parts. Fix: " + " ".join(problems)}]

    draft = (await s.execute(select(Draft).where(Draft.job_id == job.id))).scalar_one_or_none() or Draft(
        user_id=user_id, job_id=job.id
    )
    draft.resume_id, draft.template_name, draft.to_emails = resume.id, tpl.name, list(job.hr_emails)
    draft.subject, draft.body, draft.issues = subject, body, problems
    draft.status = "needs_review" if problems else "draft"
    s.add(draft)
    await s.commit()
    return draft


def word_bounds(jinja: str, fixed: dict) -> tuple[int, int]:
    """The AI's share of words stays as approved (150-220 in total with the default template); a longer or shorter
    template moves both ends by its own fixed words."""
    empty = fixed | {"opening_line": "", "closing_line": "", "fit_bullets": []}
    own = word_count(render(jinja, **empty)[1])
    default = word_count(render(default_template(), **empty)[1])
    return MIN_WORDS + own - default, MAX_WORDS + own - default


async def outdated_reason(s: AsyncSession, draft: Draft) -> str | None:
    """'resume' / 'template' when the draft was written with an older one (then it must be rewritten), else None."""
    active = await active_resume(s, draft.user_id)
    if active is None or active.id != draft.resume_id:
        return "resume"
    if draft.template_name != (await templates.active(s, draft.user_id)).name:
        return "template"
    return None


async def is_outdated(s: AsyncSession, draft: Draft) -> bool:
    return await outdated_reason(s, draft) is not None


async def email_jobs_needing_drafts(
    s: AsyncSession, user_id: uuid.UUID, since: datetime, until: datetime
) -> list[int]:
    """Email jobs of a period worth applying to (scored, not SKIP) with no draft or an outdated one, best first."""
    active = await active_resume(s, user_id)
    tpl_name = (await templates.active(s, user_id)).name
    q = (
        select(Job.id)
        .join(Post, Job.post_id == Post.id)
        .outerjoin(Draft, Draft.job_id == Job.id)
        .where(
            Job.user_id == user_id, Post.posted_at >= since, Post.posted_at < until, Job.apply_method == "email",
            Job.fit_score.is_not(None), Job.verdict != "SKIP",
            or_(Draft.id.is_(None), Draft.resume_id != (active.id if active else -1), Draft.template_name != tpl_name),
        )
        .order_by(Job.fit_score.desc(), Job.id)
    )
    return list((await s.execute(q)).scalars())
