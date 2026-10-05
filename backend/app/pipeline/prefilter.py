"""Stage 1: no AI: keep posts you can apply to (HR email or apply link); hash text for repost dedupe."""

import hashlib
import re
from dataclasses import dataclass

from email_validator import EmailNotValidError, validate_email

_LOCAL = r"[A-Za-z0-9._%+-]+"
_LABEL = r"[A-Za-z0-9-]+"
PLAIN = re.compile(rf"{_LOCAL}@{_LABEL}(?:\.{_LABEL})*\.[A-Za-z]{{2,}}")

_BR_AT = r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*"
_BR_DOT = r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*"
_WORD_DOT = r"\s+dot\s+"
# "hr [at] acme [dot] com", "hr(at)acme.com", bracketed "at", any dot style
BRACKET_AT = re.compile(rf"({_LOCAL}){_BR_AT}({_LABEL}(?:(?:{_BR_DOT}|{_WORD_DOT}|\.){_LABEL})+)", re.I)
# "priya at acme dot io": bare "at" only counts with an obfuscated dot (so "apply at site.com" isn't an email)
WORD_AT = re.compile(rf"({_LOCAL})\s+at\s+({_LABEL}(?:(?:{_BR_DOT}|{_WORD_DOT}){_LABEL})+)", re.I)
_ANY_DOT = re.compile(rf"{_BR_DOT}|{_WORD_DOT}", re.I)

URL = re.compile(r"https?://[^\s<>\"'|]+", re.I)
# short links often written without https://, only well-known ones, so "site.com" text isn't a link
BARE = re.compile(r"(?<![\w/.@])(?:forms\.gle|lnkd\.in|bit\.ly|tinyurl\.com|rb\.gy)/[^\s<>\"'|]+", re.I)
TELEGRAM = re.compile(r"^https?://(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/", re.I)  # channel links, not jobs


@dataclass(frozen=True)
class PrefilterResult:
    keep: bool
    reason: str | None  # "no_apply_method" when dropped
    emails: list[str]
    links: list[str]
    text_hash: str


def _valid(addr: str) -> str | None:
    try:
        return validate_email(addr, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


def find_emails(text: str) -> list[str]:
    found = [m.group(0) for m in PLAIN.finditer(text)]
    for pattern in (BRACKET_AT, WORD_AT):
        found += [f"{m.group(1)}@{_ANY_DOT.sub('.', m.group(2))}" for m in pattern.finditer(text)]
    out: list[str] = []
    for addr in found:
        if (email := _valid(addr.strip("."))) and email not in out:
            out.append(email)
    return out


def find_links(text: str) -> list[str]:
    """Apply links (job portals, Google Forms…) in order of appearance; Telegram links excluded."""
    found = sorted([*URL.finditer(text), *BARE.finditer(text)], key=lambda m: m.start())
    out: list[str] = []
    for m in found:
        url = m.group(0).rstrip(".,;:!?)]}>'\"")
        url = url if url.lower().startswith("http") else f"https://{url}"
        if not TELEGRAM.match(url) and url not in out:
            out.append(url)
    return out


def normalize_hash(text: str) -> str:
    """Same post reposted with other emojis/case/spacing → same hash."""
    norm = " ".join(re.sub(r"[\W_]+", " ", text.lower()).split())
    return hashlib.sha256(norm.encode()).hexdigest()


def prefilter(text: str) -> PrefilterResult:
    emails, links = find_emails(text), find_links(text)
    keep = bool(emails or links)
    return PrefilterResult(keep, None if keep else "no_apply_method", emails, links, normalize_hash(text))
