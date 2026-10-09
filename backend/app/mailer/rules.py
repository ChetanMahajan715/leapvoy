"""Email parts decided by plain rules (no AI): greeting name, subject extras/override, location phrase."""

import re

SUBJECT = re.compile(
    r"\bsubject(?:\s*line)?\s*(?:[:\-–=]|\bas\b|should be)?\s*[\"“']?([^\"”'\n)]+?)[\"”')]?\s*$", re.I | re.M
)
JOB_ID = re.compile(r"\bjob\s*id\s*[:#\-]?\s*([A-Za-z0-9][\w-]*)", re.I)
IMMEDIATE = re.compile(r"\bimmediate(?:ly)?\s+join", re.I)
HONORIFIC = re.compile(r"^(mr|mrs|ms|miss|dr)\.?\s+", re.I)


def hr_first_name(hr_name: str | None) -> str | None:
    """'aditi akulwar' → 'Aditi'; None → the template writes 'Hiring Team'."""
    name = HONORIFIC.sub("", (hr_name or "").strip())
    return name.split()[0].capitalize() if name else None


def city(location: str | None) -> str | None:
    """'Delhi NCR / Gurugram' → 'Delhi NCR'."""
    first = re.split(r"[,/|(]", location or "")[0].strip()
    return first or None


def _is_home(location: str | None, home: str) -> bool:
    return bool(location and home and home.lower() in location.lower())


def subject_parts(job, profile: dict, post_text: str) -> tuple[str | None, str]:
    """→ (subject_override, subject_extras). A subject the post requires is used exactly."""
    if job.apply_instructions and (m := SUBJECT.search(job.apply_instructions)):
        return m.group(1).strip(), ""
    home = profile.get("home_city", "")
    extras = ""
    if _is_home(job.location, home) or IMMEDIATE.search(post_text):
        place = home if _is_home(job.location, home) else city(job.location) or home
        remote = job.work_mode == "remote" or place.strip().lower() in ("remote", "work from home", "wfh")
        extras += (" | Immediate Joiner" if remote else f" | {place} | Immediate Joiner")  # "| Remote |" seen 9 Oct
    if m := JOB_ID.search(f"{job.apply_instructions or ''}\n{post_text}"):
        extras += f" | Job ID {m.group(1)}"
    return None, extras


def closing_line(job, profile: dict) -> str:
    """The email's closing sentence, built from the profile (never written by the AI, user's choice 9 Oct):
    "I am a 2026 batch BCA (Cloud Computing and System Administration) graduate, immediately available, and based
    in Pune." Education gets "graduate" if missing; "Immediate Joiner" style availability reads "immediately available"."""
    edu = " ".join(str(profile.get("education", "")).replace("&", "and").split()).rstrip(".")
    if edu and not edu.lower().endswith(("graduate", "student", "graduated")):
        edu += " graduate"
    avail = " ".join(str(profile.get("availability", "")).split()).rstrip(".")
    if "immediate" in avail.lower():
        avail = "immediately available"
    elif avail and not avail.lower().startswith("available"):
        avail = f"available {avail[0].lower()}{avail[1:]}"
    parts = [p for p in (edu and f"I am a {edu}", avail, location_phrase(job, profile)) if p]
    if len(parts) == 3:
        return f"{parts[0]}, {parts[1]}, and {parts[2]}."
    return (", and ".join(parts) + ".") if parts else ""


def location_phrase(job, profile: dict) -> str:
    home = profile.get("home_city", "")
    if job.work_mode == "remote" or (job.location or "").strip().lower() in ("remote", "work from home", "wfh"):
        return "comfortable working remotely"  # the AI sometimes puts "Remote" in location (seen 9 Oct)
    if not job.location or _is_home(job.location, home):
        return f"based in {home}"
    return f"open to relocating to {city(job.location)}"
