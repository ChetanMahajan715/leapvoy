"""User's job rules, applied in code after the AI fit check (the AI reports facts; these rules decide).

- role:        target → as scored · adjacent → at most MAYBE · unrelated → SKIP
- experience:  min ≤ 1 yr (incl. "1-3 years") → as scored · min 2–4 yrs → at most MAYBE · min 5+ → SKIP
- batch:       candidate's batch not listed → at most MAYBE (+ flag)
- title backstop: an unrelated job title (QA, analyst, sales, HR…) without AI/ML words → unrelated,
  whatever the AI said (the AI doesn't always follow the role_family instructions).
Rules only lower a verdict, never raise it.
"""

import re

from app.llm.schemas import FitCheck

AI_WORDS = re.compile(
    r"\b(ai|ml|machine learning|gen ?ai|llms?|nlp|deep learning|computer vision|data scien\w*|forward deployed)\b", re.I
)
UNRELATED_TITLE = re.compile(
    r"\b(qa|quality|test(er|ing)?|business analyst|investment|financ\w*|account(s|ing|ant)?|program\w* manag\w*|"
    r"project manag\w*|product (manag\w*|support|intern|operations|design\w*)|hr|human resources|talent|recruit\w*|"
    r"sales|marketing|customer|operations|design(er)?|procurement|supply chain|content|legal)\b",
    re.I,
)
ORDER = ["SKIP", "MAYBE", "APPLY", "STRONG MATCH", "TOP PRIORITY"]  # worst → best
MAX_SCORE = {"SKIP": 39, "MAYBE": 54, "APPLY": 69, "STRONG MATCH": 84, "TOP PRIORITY": 100}


def title_is_unrelated(role: str) -> bool:
    return bool(UNRELATED_TITLE.search(role)) and not AI_WORDS.search(role)


def _cap(fit: FitCheck, ceiling: str) -> FitCheck:
    if ORDER.index(fit.verdict) <= ORDER.index(ceiling):
        return fit
    return fit.model_copy(update={"verdict": ceiling, "score": min(fit.score, MAX_SCORE[ceiling])})


def apply_rules(fit: FitCheck, role: str = "") -> FitCheck:
    if title_is_unrelated(role):
        fit = fit.model_copy(update={"role_family": "unrelated"})
    years = fit.min_years_required
    if fit.role_family == "unrelated" or (years is not None and years >= 5):
        fit = _cap(fit, "SKIP")
    if fit.role_family == "adjacent" or (years is not None and years >= 2):
        fit = _cap(fit, "MAYBE")
    if not fit.batch_eligible:
        flags = fit.flags if "batch not eligible" in fit.flags else [*fit.flags, "batch not eligible"]
        fit = _cap(fit.model_copy(update={"flags": flags}), "MAYBE")
    return fit
