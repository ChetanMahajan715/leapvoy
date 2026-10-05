"""Pydantic schemas the LLM must fill (validated by Instructor; invalid output is re-asked)."""

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["TOP PRIORITY", "STRONG MATCH", "APPLY", "MAYBE", "SKIP"]


class JobPost(BaseModel):
    company: str = Field(description="Exact company name from the post")
    role: str = Field(description="Exact role title from the post")
    hr_emails: list[str] = Field(description="Emails to send the application to, copied exactly from the post")
    apply_links: list[str] = Field(
        default_factory=list, description="Application links (job portal, Google Form) given for THIS job, copied exactly"
    )
    hr_name: str | None = Field(None, description="First name of the HR/recruiter if the post names one")
    experience: str | None = Field(None, description='Required experience or batch, e.g. "0-2 years", "2024/2025 batch"')
    location: str | None = None
    work_mode: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    must_have_skills: list[str] = Field(default_factory=list, description="Skills/tools the post asks for, post wording")
    apply_instructions: str | None = Field(
        None, description='Special instructions, e.g. required subject line "Job ID 123", "mention batch"'
    )
    salary_or_stipend: str | None = None


class ExtractedPost(BaseModel):
    jobs: list[JobPost] = Field(description="Every separate job in the post (a post can list several). Empty if none.")


class FitRow(BaseModel):
    requirement: str = Field(description="Requirement from the post, in the post's words")
    fit: Literal["Strong", "Moderate", "Weak", "Fits"]
    note: str = Field(description="Short proof from the resume, or why it is weak")


class FitCheck(BaseModel):
    score: int = Field(ge=0, le=100)
    rows: list[FitRow]
    verdict: Verdict
    role_family: Literal["target", "adjacent", "unrelated"] = Field(
        description="target = one of the candidate's target roles; adjacent = related tech role; unrelated = other field"
    )
    min_years_required: float | None = Field(
        None, description='Minimum years of work experience the post asks for ("1-3 years" → 1); null if not stated'
    )
    batch_eligible: bool = Field(True, description="False only if the post lists graduation batches that exclude the candidate's")
    matched_skills: list[str]
    gaps: list[str]
    flags: list[str] = Field(description="e.g. relocation needed, low stipend, experience gap, location")


class FitBullet(BaseModel):
    label: str = Field(description="A requirement from the job post, in the post's own words")
    proof: str = Field(description="Proof from the resume only: project/internship, tools, result")


class EmailSlots(BaseModel):
    """The only parts of the approved email template the AI writes."""

    opening_line: str = Field(description='One sentence: "The focus on <3–4 top post skills> maps closely to my background."')
    fit_bullets: list[FitBullet] = Field(min_length=3, max_length=5)
    closing_line: str = Field(description='"I am a <education>, <availability>, and <location phrase>."')
