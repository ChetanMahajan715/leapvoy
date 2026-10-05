"""A log line must never crash a worker (Windows pipes default to cp1252, which can't print e.g. arrows or emoji)."""
import io
import sys

import structlog

from app.core.logging import setup_logging


def test_logging_survives_a_console_that_cannot_print_the_text(monkeypatch):
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    setup_logging("INFO", json=False)
    structlog.get_logger().error("sender.round_failed", detail="Mumbai → Pune ✓ \U0001F680")
    sys.stdout.flush()
    assert b"sender.round_failed" in raw.getvalue()
