"""Fill an email template (Jinja2). Template text is fixed; only the given values change."""

from functools import cache
from pathlib import Path

from jinja2 import Environment, StrictUndefined

# approved default template (docs/templates is copied into the Docker image too)
DEFAULT_TEMPLATE = Path(__file__).resolve().parents[3] / "docs" / "templates" / "default_email.j2"
MIN_WORDS, MAX_WORDS = 150, 220  # approved sample emails are 177–203 words
_env = Environment(undefined=StrictUndefined, keep_trailing_newline=False, autoescape=False)  # plain-text email


@cache
def default_template() -> str:
    return DEFAULT_TEMPLATE.read_text(encoding="utf-8")


def word_count(body: str) -> int:
    return len(body.split())


def render(template: str, **values) -> tuple[str, str]:
    """→ (subject, body). A missing value raises instead of leaving a blank in an email."""
    text = _env.from_string(template).render(**values).strip("\n")
    first, _, body = text.partition("\n")
    return first.removeprefix("Subject: ").strip(), body.lstrip("\n")
