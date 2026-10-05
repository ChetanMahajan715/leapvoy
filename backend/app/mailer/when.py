"""'now' / 'tomorrow 10am' / 'monday 10am' / '2026-10-01 11:15' → an exact UTC time (read as India time)."""

from datetime import UTC, datetime

import dateparser

from app.pipeline.report import IST


def parse_when(text: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    if text.strip().lower() == "now":
        return now
    parsed = dateparser.parse(
        text,
        settings={
            "TIMEZONE": "Asia/Kolkata",
            "TO_TIMEZONE": "UTC",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": now.astimezone(IST).replace(tzinfo=None),
        },
    )
    if parsed is None:
        raise ValueError(f"Couldn't understand the time '{text}'. Try 'tomorrow 10am' or '2026-10-01 11:15'.")
    parsed = parsed.astimezone(UTC)
    if parsed < now:
        raise ValueError(f"{parsed.astimezone(IST):%d %b %I:%M %p} IST has already passed.")
    return parsed
