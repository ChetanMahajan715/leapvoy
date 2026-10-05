import pytest

from app.mailer import cli


def test_help_lists_commands(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for command in ("draft", "drafts", "sender-add", "test-mode", "approve", "cancel", "reschedule", "outbox",
                    "send-due", "replies"):
        assert command in out


def test_draft_needs_a_job_id():
    with pytest.raises(SystemExit):
        cli.main(["draft", "--email", "a@x.com"])


@pytest.mark.parametrize(("typed", "allowed"), [("YES", True), ("yes", False), ("", False), ("y", False)])
def test_going_live_needs_typing_yes(monkeypatch, typed, allowed):
    monkeypatch.setattr("builtins.input", lambda prompt="": typed)
    assert cli.confirm_live() is allowed
