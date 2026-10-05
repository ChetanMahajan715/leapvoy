import json

import pytest

from app.accounts import profile
from app.pipeline import cli
from app.telegram import store
from tests.conftest import requires_db


def test_help_lists_all_commands(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for command in ("profile-seed", "resume-add", "run", "jobs", "day"):
        assert command in out


def test_seed_file_private_keys_are_dropped(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"_note": "private", "full_name": "A", "home_city": "Pune"}), encoding="utf-8")
    assert cli.read_seed(f) == {"full_name": "A", "home_city": "Pune"}


@requires_db
async def test_profile_seed_saves_profile(sm, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: sm)
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"_note": "x", "home_city": "Pune"}), encoding="utf-8")
    await cli.profile_seed("a@x.com", f)
    async with sm() as s:
        uid = await store.get_or_create_user(s, "a@x.com")
        assert await profile.get_profile(s, uid) == {"home_city": "Pune"}


def test_apply_to_shows_email_or_link():
    from app.db.models import Job

    assert cli.apply_to(Job(apply_method="email", hr_emails=["hr@a.ai"], apply_links=[])) == "[mail] hr@a.ai"
    assert cli.apply_to(Job(apply_method="link", hr_emails=[], apply_links=["https://forms.gle/x"])) == (
        "[link] https://forms.gle/x"
    )
