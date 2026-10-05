import pytest

from app.accounts import cli


def test_help_lists_reset(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "reset" in capsys.readouterr().out


def test_reset_refuses_mismatched_or_short_passwords(monkeypatch):
    answers = iter(["a long new password", "a different password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
    with pytest.raises(SystemExit, match="don't match"):
        cli.ask_new_password()
    answers = iter(["short", "short"])
    with pytest.raises(SystemExit, match="10 characters"):
        cli.ask_new_password()
