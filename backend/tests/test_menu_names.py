"""Every place the app or the AI tells the user to go must match the real menu (WORK / SETUP / Settings).
Fails if an old path ("More → …", "Settings → Security", "Sender accounts") comes back."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD = ["More →", "Settings → Security", "Settings → Telegram", "Settings → Resumes", "Settings → Channels",
       "Settings → Email accounts", "Settings → Profile", "Settings → Templates", "Sender accounts"]
SOURCES = [*(ROOT / "backend" / "app").rglob("*.py"), *(ROOT / "backend" / "app" / "llm" / "prompts").rglob("*.md"),
           *(ROOT / "mobile" / "src").rglob("*.ts*")]


def test_no_old_menu_paths_anywhere():
    found = [f"{p.relative_to(ROOT)}: {old}" for p in SOURCES for old in OLD
             if old in p.read_text(encoding="utf-8", errors="ignore")]
    assert not found, found


def test_the_ai_knows_the_real_menu():
    prompt = (ROOT / "backend" / "app" / "llm" / "prompts" / "v1" / "chat.md").read_text(encoding="utf-8")
    for name in ("WORK", "SETUP", "Channels", "Email accounts", "Resumes", "Settings opens from"):
        assert name in prompt
