"""Build the golden-set labelling sheet from saved posts (no AI involved → independent answer key).

  uv run python scripts/dev.py python eval/export_golden.py --email me@x.com [--n 40]

Writes eval/data/golden_v1.csv (gitignored: real posts contain HR emails). One row per job.
Fix company/role/emails if the pre-fill is wrong, and fill `relevant` with y or n
("would I want to apply to this job?"). Then run eval/run_eval.py.
"""

import argparse
import asyncio
import csv
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select  # noqa: E402

from app.db.models import Post  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.pipeline.prefilter import find_emails  # noqa: E402
from app.telegram.store import get_or_create_user  # noqa: E402

OUT = Path(__file__).parent / "data" / "golden_v1.csv"
COMPANY_LINE = re.compile(r"(?im)^(?=[^\w\n]*(?:\d+\s*[).]\s*)?company\s*[-:])")  # each "Company - ..." line starts a job
HAS_COMPANY = re.compile(r"(?i)\bcompany\s*[-:]")
FIELD = r"(?i)\b{}\s*[-:]\s*([^|\n]+)"
AI = re.compile(r"\b(AI|ML|machine learning|GenAI|LLM|data scien\w*|deep learning|NLP|computer vision)\b", re.I)


def field(block: str, name: str) -> str:
    m = re.search(FIELD.format(name), block)
    return m.group(1).strip() if m else ""


def prefill(text: str) -> list[dict]:
    blocks = [b for b in COMPANY_LINE.split(text) if HAS_COMPANY.search(b)] or [text]
    # one address can serve every job only if it's the post's only address and no job applies via a link/form
    emails = find_emails(text)
    shared = emails if len(emails) == 1 and not re.search(r"https?://", text) else []
    return [
        {"company": field(b, "company"), "role": field(b, "role"), "hr_emails": " ".join(find_emails(b) or shared)}
        for b in blocks
    ]


async def main(email: str, n: int) -> None:
    async with get_sessionmaker()() as s:
        user_id = await get_or_create_user(s, email)
        posts = (await s.execute(select(Post).where(Post.user_id == user_id).order_by(Post.id))).scalars().all()
    with_email = [p for p in posts if find_emails(p.text)]
    multi = [p for p in with_email if len(prefill(p.text)) > 1]
    rest = [p for p in with_email if p not in multi]
    rng = random.Random(42)  # same sample every time
    ai = [p for p in rest if AI.search(p.text)]
    other = [p for p in rest if not AI.search(p.text)]
    picked = multi[: n // 3]
    k = (n - len(picked)) // 2
    picked += rng.sample(ai, min(k, len(ai)))
    picked += rng.sample(other, min(n - len(picked), len(other)))

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig → Excel shows emojis/₹ correctly
        w = csv.DictWriter(f, ["post_id", "job", "company", "role", "hr_emails", "relevant", "post_excerpt"])
        w.writeheader()
        for p in sorted(picked, key=lambda p: p.id):
            for i, job in enumerate(prefill(p.text)):
                w.writerow(
                    {"post_id": p.id, "job": i, **job, "relevant": "", "post_excerpt": " ".join(p.text.split())[:300]}
                )
    rows = sum(len(prefill(p.text)) for p in picked)
    n_multi = len([p for p in picked if p in multi])
    print(f"OK: {len(picked)} posts ({n_multi} multi-job) → {rows} job rows in {OUT}")


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--email", required=True)
    a.add_argument("--n", type=int, default=40)
    args = a.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(main(args.email, args.n))
