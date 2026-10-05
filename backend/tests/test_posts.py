"""'All posts' of a day (every Telegram post, newest first, Telegram's time, plain status) + professional labels."""
from datetime import timedelta

from sqlalchemy import select

from app.chat import tools
from app.db.models import Channel, Job, Post
from app.pipeline.posts import describe, verdict_label
from tests.conftest import requires_db
from tests.test_auth_api import PW, api, bearer, secrets  # noqa: F401 (fixtures)
from tests.test_outbox import NOW, master_key, setup, smtp  # noqa: F401 (fixtures)

pytestmark = requires_db


def test_professional_labels():
    assert [verdict_label(v) for v in ["TOP PRIORITY", "STRONG MATCH", "APPLY", "MAYBE", "SKIP", None]] == [
        "Excellent fit", "Strong fit", "Good fit", "Possible fit", "Not a fit", None]


async def add_posts(db, uid):
    ch = (await db.execute(select(Channel).where(Channel.user_id == uid))).scalars().first()
    rows = [
        Post(user_id=uid, channel_id=ch.id, tg_message_id=60, posted_at=NOW - timedelta(minutes=30), stage="skipped",
             skip_reason="low_match", match_score=0.6, text="Company - Blinkit\nRole - Associate Program Manager"),
        Post(user_id=uid, channel_id=ch.id, tg_message_id=61, posted_at=NOW - timedelta(minutes=20), stage="skipped",
             skip_reason="no_valid_job", text="Company - Kiwimesh\nRole - AI Generalist Intern"),
        Post(user_id=uid, channel_id=ch.id, tg_message_id=62, posted_at=NOW - timedelta(minutes=10), stage="new",
             text="Company - Fresh Co\nRole - AI Engineer"),
    ]
    db.add_all(rows)
    await db.commit()
    return ch


async def test_every_post_of_the_day_newest_first_with_a_plain_status(api, db, smtp):
    uid, [job] = await setup(db)  # its post is at NOW (newest), a STRONG MATCH job
    r = await api.post("/auth/signup", json={"email": "a@x.com", "password": PW, "device_name": "t"})
    h = bearer(r.json())
    ch = await add_posts(db, uid)
    posts = (await api.get("/posts", headers=h, params={"date": "2026-09-30"})).json()
    assert [p["tg_message_id"] for p in posts] == [1, 62, 61, 60]  # newest first
    first, fresh, kiwi, blinkit = posts
    assert first["status"] == "Strong fit · 80/100" and first["kind"] == "fit" and first["job_ids"] == [job]
    assert fresh["status"] == "Waiting for AI check" and fresh["kind"] == "pending"
    assert kiwi["status"] == "No email or apply link found" and kiwi["kind"] == "skipped"
    assert blinkit["status"] == "Weak match with your resume" and blinkit["title"] == "Blinkit · Associate Program Manager"
    assert first["posted_at"] and first["channel"] == ch.title and blinkit["text"].startswith("Company - Blinkit")


async def test_not_a_fit_says_why(db, smtp):
    uid, [job] = await setup(db)
    j = await db.get(Job, job)
    j.verdict, j.fit_score, j.flags = "SKIP", 20, ["batch not eligible", "experience gap"]
    await db.commit()
    post = await db.get(Post, j.post_id)
    d = describe(post, [j], "Jobs")
    assert d["status"] == "Not a fit: batch not eligible" and d["kind"] == "skipped"


async def test_chat_lists_all_posts_and_search_shows_them_as_post_cards(db, smtp):
    uid, [job] = await setup(db)
    await add_posts(db, uid)
    ctx = tools.Context(now=NOW, incognito=False, last_user_message="")
    r = await tools.run_tool(db, uid, "list_posts", {"date": "2026-09-30"}, ctx)
    assert r.card["type"] == "posts" and len(r.card["post_ids"]) == 4 and "4 post" in r.text and "9:30 AM" in r.text
    r = await tools.run_tool(db, uid, "search_posts", {"query": "blinkit"}, ctx)
    assert r.card["type"] == "posts" and len(r.card["post_ids"]) == 1
    assert "Weak match with your resume" in r.text


async def test_posts_by_ids_for_chat_cards_and_other_users_cant_see_them(api, db, smtp):
    uid, _ = await setup(db, email="a@x.com")
    await add_posts(db, uid)
    ids = (await db.execute(select(Post.id).where(Post.user_id == uid).order_by(Post.id))).scalars().all()
    other = bearer((await api.post("/auth/signup", json={"email": "b@x.com", "password": PW, "device_name": "t"})).json())
    assert (await api.get("/posts", headers=other, params={"ids": ",".join(map(str, ids))})).json() == []


async def test_posts_carry_their_full_job_cards_and_how_to_apply(api, db, smtp):
    """All posts shows the same job cards as Recommended (select, write, send), and Email / Link filters."""
    uid, [job] = await setup(db, email="a@x.com")
    await add_posts(db, uid)
    kiwi = (await db.execute(select(Post).where(Post.tg_message_id == 61))).scalar_one()
    kiwi.emails, kiwi.links = [], ["https://forms.gle/k"]
    await db.commit()
    h = bearer((await api.post("/auth/signup", json={"email": "a@x.com", "password": PW, "device_name": "t"})).json())
    posts = {p["tg_message_id"]: p for p in (await api.get("/posts", headers=h, params={"date": "2026-09-30"})).json()}
    assert [j["id"] for j in posts[1]["jobs"]] == [job] and posts[1]["jobs"][0]["hr_emails"]
    assert posts[61]["jobs"] == [] and posts[61]["has_link"] and not posts[61]["has_email"]


def test_title_takes_company_and_role_lines_only():
    from app.pipeline.posts import post_title
    assert post_title("Company - Fresh Co\nRole - AI Engineer\nMail jobs@fresh.co") == "Fresh Co · AI Engineer"
    assert post_title("🚀 Hiring!\nCompany Name: Acme\nRole: ML Intern (Remote)\nApply: x") == "Acme · ML Intern (Remote)"
    assert post_title("Big news\nWe are hiring") == "Big news"


async def test_failed_and_waiting_posts_say_so_honestly(db, smtp):
    uid, _ = await setup(db)
    ch = await add_posts(db, uid)
    failed = Post(user_id=uid, channel_id=ch.id, tg_message_id=70, posted_at=NOW, stage="error",
                  skip_reason="error: LLMUnavailable", text="Company - Park+\nRole - Intern", links=["https://forms.gle/p"])
    db.add(failed)
    await db.commit()
    assert describe(failed, [], "Jobs")["kind"] == "failed"
    assert describe(failed, [], "Jobs")["status"] == "AI check failed. Try again"
    fresh = (await db.execute(select(Post).where(Post.tg_message_id == 62))).scalar_one()
    assert describe(fresh, [], "Jobs")["status"] == "Waiting for AI check"
    assert describe(failed, [], "Jobs")["links"] == ["https://forms.gle/p"]


async def test_check_again_reruns_a_failed_post(api, db, smtp, monkeypatch):
    uid, _ = await setup(db, email="a@x.com")
    ch = (await db.execute(select(Channel).where(Channel.user_id == uid))).scalars().first()
    failed = Post(user_id=uid, channel_id=ch.id, tg_message_id=70, posted_at=NOW, stage="error", attempts=3,
                  skip_reason="error: LLMUnavailable", text="Company - Park+\nRole - Intern")
    db.add(failed)
    await db.commit()
    seen = {}

    async def fake_run(sm, post_id):
        async with sm() as s:
            p = await s.get(Post, post_id)
            seen["stage"], seen["attempts"] = p.stage, p.attempts
            p.stage, p.skip_reason = "skipped", "low_match"
            await s.commit()
        return "skipped"

    from app.pipeline import graph
    monkeypatch.setattr(graph, "run_post", fake_run)
    h = bearer((await api.post("/auth/signup", json={"email": "a@x.com", "password": PW, "device_name": "t"})).json())
    r = await api.post(f"/posts/{failed.id}/check", headers=h)
    assert r.status_code == 200 and seen == {"stage": "new", "attempts": 0}
    assert r.json()["status"] == "Weak match with your resume"
    other = bearer((await api.post("/auth/signup", json={"email": "b@x.com", "password": PW, "device_name": "t"})).json())
    assert (await api.post(f"/posts/{failed.id}/check", headers=other)).status_code == 404


async def test_force_reads_a_skipped_post_so_it_can_get_an_email(api, db, smtp, monkeypatch):
    """'Write email' on a weak-match post: the AI reads it anyway (past the resume-match gate)."""
    uid, _ = await setup(db, email="a@x.com")
    await add_posts(db, uid)
    blinkit = (await db.execute(select(Post).where(Post.tg_message_id == 60))).scalar_one()
    seen = {}

    async def fake_run(sm, post_id):
        async with sm() as s:
            seen["stage"] = (await s.get(Post, post_id)).stage
        return "scored"

    from app.pipeline import graph
    monkeypatch.setattr(graph, "run_post", fake_run)
    h = bearer((await api.post("/auth/signup", json={"email": "a@x.com", "password": PW, "device_name": "t"})).json())
    assert (await api.post(f"/posts/{blinkit.id}/check", headers=h, json={"force": True})).status_code == 200
    assert seen["stage"] == "matched"


async def test_opening_a_day_checks_its_waiting_posts_automatically(api, db, smtp, monkeypatch):
    """No 'Check now' button: the app asks the server to check that day's waiting posts by itself."""
    from app.chat import tools as chat_tools
    from app.llm import usage
    from app.pipeline import graph
    uid, _ = await setup(db, email="a@x.com")
    await add_posts(db, uid)  # tg 62 'Fresh Co' is waiting (stage new)
    ran = []

    async def fake_run(sm, post_id):
        ran.append(post_id)
        async with sm() as s:
            p = await s.get(Post, post_id)
            p.stage, p.skip_reason = "skipped", "low_match"
            await s.commit()
        return "skipped"

    async def allowed(s, now):
        return True

    monkeypatch.setattr(graph, "run_post", fake_run)
    monkeypatch.setattr(usage, "background_allowed", allowed)
    h = bearer((await api.post("/auth/signup", json={"email": "a@x.com", "password": PW, "device_name": "t"})).json())
    r = (await api.post("/posts/check-day", headers=h, json={"date": "2026-09-30"})).json()
    assert r == {"checked": 1, "waiting": 0, "paused": False} and len(ran) == 1
    fresh = next(p for p in (await api.get("/posts", headers=h, params={"date": "2026-09-30"})).json() if p["tg_message_id"] == 62)
    assert fresh["status"] == "Weak match with your resume"
    other = bearer((await api.post("/auth/signup", json={"email": "b@x.com", "password": PW, "device_name": "t"})).json())
    assert (await api.post("/posts/check-day", headers=other, json={"date": "2026-09-30"})).json()["checked"] == 0

    async def exhausted(s, now):
        return False

    monkeypatch.setattr(usage, "background_allowed", exhausted)
    db.add(Post(user_id=uid, channel_id=(await db.execute(select(Channel.id).where(Channel.user_id == uid))).scalars().first(),
                tg_message_id=90, posted_at=NOW, stage="new", text="Company - Later\nRole - AI Engineer"))
    await db.commit()
    r = (await api.post("/posts/check-day", headers=h, json={"date": "2026-09-30"})).json()
    assert r == {"checked": 0, "waiting": 1, "paused": True}  # free AI used up: waits for the refill, says so
    assert chat_tools.FETCH_SECONDS >= 20
