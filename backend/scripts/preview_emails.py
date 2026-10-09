"""Write sample emails with the current code for the best email jobs, WITHOUT saving anything (one transaction,
rolled back at the end). Used to show the user new email wording before it goes live.

Run on the server with the new code mounted over the image's (no restart of the live app):
  docker compose --env-file .env -f deploy/docker-compose.yml run --rm -v ~/preview/backend:/app/backend backend \
      python scripts/preview_emails.py 3
"""

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.db.models import Job
from app.mailer import drafts

GOOD = ("TOP PRIORITY", "STRONG MATCH", "APPLY")


async def main(n: int) -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
        jobs = (await s.execute(select(Job).where(Job.apply_method == "email", Job.verdict.in_(GOOD))
                                .order_by(Job.fit_score.desc(), Job.id.desc()).limit(n))).scalars().all()
        for job in jobs:
            d = await drafts.write_draft(s, job.user_id, job.id)
            print("=" * 72)
            print(f"{job.role} · {job.company} · fit {job.fit_score} · {d.status}"
                  + (f" · needs review: {'; '.join(d.issues)}" if d.issues else ""))
            print("-" * 72)
            print(f"Subject: {d.subject}\n\n{d.body}")
        await outer.rollback()  # nothing is kept
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3))
