from datetime import UTC, date, datetime

from sqlalchemy import select, update

from app.db.models import Job, Post
from app.pipeline import report
from app.pipeline import store as pstore
from app.telegram import store
from app.telegram.store import IncomingPost
from tests.conftest import requires_db


def test_day_is_midnight_to_midnight_india_time():
    start, end = report.day_bounds(date(2026, 9, 29))
    assert start == datetime(2026, 9, 28, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 9, 29, 18, 30, tzinfo=UTC)


def test_parse_day_words_and_dates():
    now = date(2026, 9, 29)
    assert report.parse_day("today", now) == date(2026, 9, 29)
    assert report.parse_day("yesterday", now) == date(2026, 9, 28)
    assert report.parse_day("2026-09-27", now) == date(2026, 9, 27)


async def seed(db, email="a@x.com", chat_id=-1001):
    uid = await store.get_or_create_user(db, email)
    await store.upsert_channels(db, uid, [(chat_id, "Jobs", None)])
    await store.set_enabled(db, uid, [chat_id], True)
    ch = await store.get_enabled_channel(db, uid, chat_id)
    posts = [
        IncomingPost(1, "late on 28th IST", datetime(2026, 9, 28, 18, 20, tzinfo=UTC)),  # 23:50 IST 28 Sep
        IncomingPost(2, "just after midnight", datetime(2026, 9, 28, 19, 0, tzinfo=UTC)),  # 00:30 IST 29 Sep
        IncomingPost(3, "evening post", datetime(2026, 9, 29, 16, 0, tzinfo=UTC)),  # 21:30 IST 29 Sep
        IncomingPost(4, "after midnight 30th", datetime(2026, 9, 29, 18, 45, tzinfo=UTC)),  # 00:15 IST 30 Sep
    ]
    await store.save_posts(db, uid, ch.id, posts)
    ids = (await db.execute(select(Post.id).where(Post.user_id == uid).order_by(Post.tg_message_id))).scalars().all()
    return uid, ids


async def add_job(db, uid, post_id, company, score, verdict, idx=0):
    db.add(Job(user_id=uid, post_id=post_id, idx=idx, company=company, role="AI Engineer", hr_emails=["hr@x.ai"],
               fit_score=score, verdict=verdict))
    await db.commit()


@requires_db
async def test_all_posts_of_the_day_in_india_time(db):
    uid, _ = await seed(db)
    r = await report.day_report(db, uid, date(2026, 9, 29))
    assert [p.text for p in r.posts] == ["just after midnight", "evening post"]


@requires_db
async def test_resume_matches_best_first_without_skips(db):
    uid, ids = await seed(db)
    await add_job(db, uid, ids[1], "Acme", 71, "STRONG MATCH")
    await add_job(db, uid, ids[2], "Zeta", 90, "TOP PRIORITY")
    await add_job(db, uid, ids[2], "Nope", 80, "SKIP", idx=1)  # e.g. needs 3+ years
    await add_job(db, uid, ids[3], "Tomorrow", 99, "TOP PRIORITY")  # 30 Sep IST → not today
    r = await report.day_report(db, uid, date(2026, 9, 29))
    assert [j.company for j, _ in r.matches] == ["Zeta", "Acme"]


@requires_db
async def test_counts_posts_still_being_processed(db):
    uid, ids = await seed(db)
    await db.execute(update(Post).where(Post.id == ids[1]).values(stage="scored"))
    await db.commit()
    r = await report.day_report(db, uid, date(2026, 9, 29))
    assert r.pending == 1  # "evening post" is still stage=new


@requires_db
async def test_pending_posts_can_be_limited_to_one_day(db):
    uid, ids = await seed(db)
    start, end = report.day_bounds(date(2026, 9, 29))
    assert await pstore.next_posts(db, uid, 10, since=start, until=end) == [ids[1], ids[2]]
    assert await pstore.next_posts(db, uid, 10) == ids  # no range → everything pending


@requires_db
async def test_other_users_posts_never_appear(db):
    await seed(db, "a@x.com", -1001)
    b = await store.get_or_create_user(db, "b@x.com")
    r = await report.day_report(db, b, date(2026, 9, 29))
    assert (r.posts, r.matches, r.pending) == ([], [], 0)
