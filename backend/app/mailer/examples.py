"""The 3 approved real sample emails (docs/templates/Leapvoy-Default-Email-Template.md): used as style examples
for the AI and as exact-output tests for the template."""

import re
from functools import cache
from pathlib import Path

DOC = Path(__file__).resolve().parents[3] / "docs" / "templates" / "Leapvoy-Default-Email-Template.md"


@cache
def load() -> list[str]:
    section = DOC.read_text(encoding="utf-8").split("## 5. Examples")[1]
    return [b.strip("\n") for b in re.findall(r"```\n(.*?)```", section, re.S)]


def slots_from(email: str) -> dict:
    """Take a finished example email apart into the values the template is filled with."""
    lines = email.split("\n")
    role, company, opening = re.search(r"apply for the (.+) role at (.+?)\. (.+)$", email, re.M).groups()
    name, phone = lines[-2], lines[-1]
    subject = lines[0].removeprefix("Subject: ")
    closing = lines[[i for i, line in enumerate(lines) if line.startswith("GitHub:")][0] - 2]
    hr = re.search(r"^Dear (.+),$", email, re.M).group(1)
    return {
        "role": role,
        "company": company,
        "opening_line": opening,
        "closing_line": closing,
        "hr_first_name": None if hr == "Hiring Team" else hr,
        "subject_extras": subject.removeprefix(f"Application for {role} - {name}"),
        "subject_override": None,
        "fit_bullets": [
            dict(zip(("label", "proof"), line[2:].split(": ", 1), strict=True)) for line in lines if line.startswith("- ")
        ],
        "profile": {
            "full_name": name,
            "phone": phone,
            "github_url": re.search(r"^GitHub: (.+)$", email, re.M).group(1),
            "linkedin_url": re.search(r"^LinkedIn: (.+)$", email, re.M).group(1),
        },
    }
