"""The user's own email template: plain text with {tags} (no template code), saved as versions.
Tags become fixed Jinja snippets here, so user text can never run template code. Unchanged = the approved default."""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EmailTemplate

DEFAULT_NAME = "default-v1"
MAX_CHARS = 4000

# the approved template (docs/templates/default_email.j2) in tag form; tests check both give the same email
DEFAULT_TEXT = """Subject: Application for {role} - {name}

Dear {hr_name},

I am writing to apply for the {role} role at {company}. {opening_line}

Why I am a strong fit:

{fit_bullets}

{closing_line}

GitHub: {github}
LinkedIn: {linkedin}

I have attached my resume and look forward to hearing from you.

Best regards,
{name}
{phone}"""

# tag → (what the app shows, the fixed Jinja it becomes)
TAGS: dict[str, tuple[str, str]] = {
    "role": ("the job's role", "{{ role }}"),
    "company": ("the company", '{{ company | trim | trim(".") }}'),
    "hr_name": ("HR's first name, or 'Hiring Team'", '{{ hr_first_name or "Hiring Team" }}'),
    "name": ("your full name", "{{ profile.full_name }}"),
    "phone": ("your phone", "{{ profile.phone }}"),
    "linkedin": ("your LinkedIn link", "{{ profile.linkedin_url }}"),
    "github": ("your GitHub link", "{{ profile.github_url }}"),
    "opening_line": ("AI: why this role fits you (1-2 sentences)", "{{ opening_line }}"),
    "fit_bullets": ("AI: 3-4 'skill: proof' lines from your resume",
                    "{% for b in fit_bullets %}- {{ b.label }}: {{ b.proof }}{% if not loop.last %}\n{% endif %}{% endfor %}"),
    "closing_line": ("AI: availability and location line", "{{ closing_line }}"),
}
AI_TAGS = ("opening_line", "fit_bullets", "closing_line")
_TAG = re.compile(r"\{([a-z_]+)\}")


class TemplateError(ValueError):
    pass


class TemplateNotFound(LookupError):
    pass


def _jinja(part: str) -> str:
    return _TAG.sub(lambda m: TAGS[m.group(1)][1], part)


def to_jinja(text: str) -> str:
    """Check the user's text and turn it into the Jinja the renderer uses. Raises TemplateError with a plain reason."""
    text = text.replace("\r\n", "\n").strip()
    if len(text) > MAX_CHARS:
        raise TemplateError(f"The template is too long (max {MAX_CHARS} characters).")
    first, _, body = text.partition("\n")
    if not first.lower().startswith("subject:") or not first[8:].strip():
        raise TemplateError("The first line must be the subject, like: Subject: Application for {role} - {name}")
    if any(x in text for x in ("{{", "{%", "{#")):
        raise TemplateError("Use only tags like {role} in curly braces; no other template code.")
    unknown = sorted({t for t in _TAG.findall(text) if t not in TAGS})
    if unknown:
        raise TemplateError(f"Unknown tag {{{unknown[0]}}}. Use one of: " + ", ".join(f"{{{t}}}" for t in TAGS))
    if re.search(r"[{}]", _TAG.sub("", text)):
        raise TemplateError("Curly braces are only for tags like {role}.")
    for tag in AI_TAGS:
        n = _TAG.findall(body).count(tag)
        if n == 0:
            raise TemplateError(f"Keep {{{tag}}} in the email body: the AI writes that part from your resume.")
        if n > 1:
            raise TemplateError(f"Use {{{tag}}} only once.")
        if tag in _TAG.findall(first):
            raise TemplateError(f"{{{tag}}} belongs in the body, not the subject.")
    if not any(line.strip() == "{fit_bullets}" for line in body.split("\n")):
        raise TemplateError("Put {fit_bullets} on its own line (it becomes several lines).")
    subject = first[8:].strip()
    return ("Subject: {% if subject_override %}{{ subject_override }}{% else %}" + _jinja(subject)
            + '{{ subject_extras or "" }}{% endif %}\n' + _jinja(body))


@dataclass(frozen=True)
class Active:
    name: str  # "default-v1" or "custom-v3" (stored on each draft)
    text: str  # the {tags} text shown in the editor
    jinja: str


async def active(s: AsyncSession, user_id: uuid.UUID) -> Active:
    row = (await s.execute(select(EmailTemplate).where(EmailTemplate.user_id == user_id, EmailTemplate.is_active))
           ).scalar_one_or_none()
    if row is None:
        return Active(DEFAULT_NAME, DEFAULT_TEXT, to_jinja(DEFAULT_TEXT))
    return Active(f"custom-v{row.version}", row.text, to_jinja(row.text))


async def versions(s: AsyncSession, user_id: uuid.UUID) -> list[EmailTemplate]:
    return list((await s.execute(select(EmailTemplate).where(EmailTemplate.user_id == user_id)
                                 .order_by(EmailTemplate.version.desc()))).scalars())


async def save(s: AsyncSession, user_id: uuid.UUID, text: str) -> EmailTemplate:
    """New version, made active. Raises TemplateError for a broken template (nothing saved)."""
    text = text.replace("\r\n", "\n").strip()
    to_jinja(text)
    n = await s.scalar(select(func.coalesce(func.max(EmailTemplate.version), 0)).where(EmailTemplate.user_id == user_id))
    await s.execute(update(EmailTemplate).where(EmailTemplate.user_id == user_id).values(is_active=False))
    row = EmailTemplate(user_id=user_id, version=n + 1, text=text, is_active=True)
    s.add(row)
    await s.commit()
    return row


async def activate(s: AsyncSession, user_id: uuid.UUID, template_id: int) -> EmailTemplate:
    row = (await s.execute(select(EmailTemplate).where(EmailTemplate.id == template_id,
                                                       EmailTemplate.user_id == user_id))).scalar_one_or_none()
    if row is None:
        raise TemplateNotFound(template_id)
    await s.execute(update(EmailTemplate).where(EmailTemplate.user_id == user_id).values(is_active=False))
    row.is_active = True
    await s.commit()
    return row


async def use_default(s: AsyncSession, user_id: uuid.UUID) -> None:
    await s.execute(update(EmailTemplate).where(EmailTemplate.user_id == user_id).values(is_active=False))
    await s.commit()
