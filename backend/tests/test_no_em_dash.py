"""The user never wants to see the em dash character: not in AI chat answers, not anywhere in the app."""
from app.chat.agent import no_em_dash

EM = chr(0x2014)


def test_chat_text_chunks_lose_em_dashes():
    assert no_em_dash(f"Allvest fits best {EM} 81/100.") == "Allvest fits best - 81/100."
    assert no_em_dash(f"a{EM}b") == "a-b" and no_em_dash("plain") == "plain"


def test_no_file_in_the_project_contains_an_em_dash():
    """Code, comments, UI text, docs, prompts: every file git tracks (the user's rule, 3 Oct)."""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    files = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout.split(b"\0")
    bad = [f.decode() for f in files if f and (root / f.decode()).is_file()
           and EM.encode() in (root / f.decode()).read_bytes()]
    assert bad == [], f"em dash found in: {bad}"
