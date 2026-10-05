from datetime import UTC, datetime

import pytest

from app.mailer.when import parse_when

NOW = datetime(2026, 9, 29, 15, 30, tzinfo=UTC)  # Tue 29 Sep 2026, 9:00 PM India time


def ist(day, hour, minute=0):
    return datetime(2026, *day, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize(("text", "expected"), [
    ("now", NOW),
    ("tomorrow 10am", datetime(2026, 9, 30, 4, 30, tzinfo=UTC)),  # 10:00 IST
    ("tomorrow 6 pm", datetime(2026, 9, 30, 12, 30, tzinfo=UTC)),
    ("monday 10am", datetime(2026, 10, 5, 4, 30, tzinfo=UTC)),
    ("2026-10-01 11:15", datetime(2026, 10, 1, 5, 45, tzinfo=UTC)),
    ("1 Oct 11:15 am", datetime(2026, 10, 1, 5, 45, tzinfo=UTC)),
    ("today 11pm", datetime(2026, 9, 29, 17, 30, tzinfo=UTC)),
    ("in 1 hour", datetime(2026, 9, 29, 16, 30, tzinfo=UTC)),  # Scheduled screen "+1 hour"
])
def test_times_are_india_time(text, expected):
    assert parse_when(text, NOW) == expected


def test_past_time_is_refused():
    with pytest.raises(ValueError, match="already passed"):
        parse_when("today 6pm", NOW)


def test_nonsense_is_refused():
    with pytest.raises(ValueError, match="understand"):
        parse_when("whenever you feel like it", NOW)
