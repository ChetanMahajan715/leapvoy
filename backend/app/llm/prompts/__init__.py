from functools import cache
from pathlib import Path

VERSION = "v1"  # bump to a new folder when prompts change, so eval runs can compare versions


@cache
def load(name: str) -> str:
    return (Path(__file__).parent / VERSION / f"{name}.md").read_text(encoding="utf-8")
