"""One Telegram post often lists many jobs ("1) Company - A ... 2) Company - B ..."). These helpers cut a post into
one block per job: used to match each job against the resume, to score each job on its own text, and to show a job
card only its own part of the post. Plain text rules, no AI."""

import re

# "1)", "2.", "3:", "#4", "Job 5 -", or a keycap emoji like 1️⃣, at the start of a line (after up to 4 symbols/emoji)
_NUMBERED = re.compile(r"^[^\w\n]{0,4}(?:#|job\s*)?(\d{1,2})(?:️?⃣|\s*[).:\]]|\s+-)", re.I | re.M)
_COMPANY = re.compile(r"^[^\w\n]{0,4}company(?:\s*name)?\s*[:\-–]", re.I | re.M)
_JOB_WORDS = re.compile(r"\b(company|role|position|designation|hiring|opening|job)\b", re.I)


def _cut(text: str, starts: list[int]) -> list[str]:
    return [text[a:b].strip() for a, b in zip(starts, [*starts[1:], len(text)], strict=True)]


def split_jobs(text: str) -> list[str]:
    """One block per job, or [] when the post holds a single job (or no clear list)."""
    numbered = list(_NUMBERED.finditer(text))
    nums = [int(m.group(1)) for m in numbered]
    if len(numbered) >= 2 and all(b > a for a, b in zip(nums, nums[1:])):  # 1, 2, 3 ... (a list, not dates)
        parts = _cut(text, [m.start() for m in numbered])
        if all(_JOB_WORDS.search(p) for p in parts):  # each block describes a job, not "1. Python 2. SQL"
            return parts
    companies = [m.start() for m in _COMPANY.finditer(text)]
    return _cut(text, companies) if len(companies) >= 2 else []


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def _block_for(parts: list[str], jobs: list[tuple[str, str]], i: int) -> str | None:
    if len(parts) == len(jobs):
        return parts[i]  # the AI lists jobs in post order
    company, role = jobs[i]
    want = _words(company) | _words(role)
    best = max(parts, key=lambda p: len(want & _words(p)))
    return best if want & _words(best) else None


def excerpt(text: str, jobs: list[tuple[str, str]], i: int, emails: list[str], links: list[str]) -> str:
    """Job i's own part of the post. If its HR email / apply link is only elsewhere (e.g. one 'Apply here' line at the
    end for every job), that line is added, so the card still shows how to apply. Whole post when it can't be cut."""
    parts = split_jobs(text)
    block = _block_for(parts, jobs, i) if parts else None
    if block is None:
        return text.strip()
    extra: list[str] = []
    for needle in [*emails, *links]:
        if needle.lower() not in block.lower():
            line = next((ln.strip() for ln in text.splitlines() if needle.lower() in ln.lower()), None)
            if line and line not in extra and line not in block:
                extra.append(line)
    return "\n\n".join([block, *extra]) if extra else block
