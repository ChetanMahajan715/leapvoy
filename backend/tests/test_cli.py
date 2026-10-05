import base64

import pytest

from app.telegram import cli


def test_help_lists_all_commands(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for command in ("keygen", "login", "channels", "enable", "disable", "backfill", "logout"):
        assert command in out


def test_keygen_prints_a_32_byte_base64_key(capsys):
    cli.main(["keygen"])
    key = capsys.readouterr().out.strip().removeprefix("MASTER_KEY=")
    assert len(base64.b64decode(key)) == 32


def test_enable_needs_chat_ids():
    with pytest.raises(SystemExit):
        cli.main(["enable", "--email", "a@x.com"])
