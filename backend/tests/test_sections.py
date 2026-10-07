from datetime import UTC, datetime

from app.api.jobs import job_json
from app.db.models import Channel, Job, Post, Resume
from app.pipeline.sections import excerpt, split_jobs
from app.telegram import store
from tests.conftest import requires_db

MULTI = """🔥 Referral Alert 🔥

1) Company - iRage
Role - Software Developer Intern
Batch - 2027/2028

2) Company - iRage
Role - Quantitative Analyst Intern
Batch - 2027/2028

3) Company - Haus Of Brands
Role - Business Analyst
Apply - hr@hausofbrands.com

Share with your friends!"""


def test_numbered_post_splits_into_jobs():
    parts = split_jobs(MULTI)
    assert len(parts) == 3
    assert parts[0].startswith("1) Company - iRage") and "Software Developer" in parts[0]
    assert "Quantitative" in parts[1] and "Software Developer" not in parts[1]
    assert "Referral Alert" not in "".join(parts)  # the shared header belongs to no job


def test_keycap_and_company_lines():
    keycaps = "Hiring!\n1️⃣ Company: A\nRole: ML Engineer\n2️⃣ Company: B\nRole: Data Scientist"
    assert len(split_jobs(keycaps)) == 2
    unnumbered = "Company: Alpha\nRole: AI Engineer\nApply: a@x.com\n\nCompany: Beta\nRole: ML Intern\nApply: b@y.com"
    assert [p.split("\n")[0] for p in split_jobs(unnumbered)] == ["Company: Alpha", "Company: Beta"]


def test_numbered_requirements_of_one_job_do_not_split():
    one = "Company - Acme\nRole - AI Engineer\nRequirements:\n1. Python\n2. PyTorch\n3. SQL\nApply: hr@acme.com"
    assert split_jobs(one) == []


def test_any_number_of_jobs():
    big = "\n\n".join(f"{i}) Company - C{i}\nRole - Role {i}" for i in range(1, 16))
    assert len(split_jobs(big)) == 15


def test_excerpt_is_only_that_job_plus_shared_apply_line():
    post = MULTI + "\n\nApply for all: https://forms.gle/abc"
    jobs = [("iRage", "Software Developer Intern"), ("iRage", "Quantitative Analyst Intern"),
            ("Haus Of Brands", "Business Analyst")]
    quant = excerpt(post, jobs, 1, emails=[], links=["https://forms.gle/abc"])
    assert "Quantitative" in quant and "Software Developer" not in quant and "Haus" not in quant
    assert quant.endswith("Apply for all: https://forms.gle/abc")  # how to apply was only at the end
    haus = excerpt(post, jobs, 2, emails=["hr@hausofbrands.com"], links=[])
    assert "Haus Of Brands" in haus and "iRage" not in haus
    assert haus.count("forms.gle") == 1  # the last block runs to the end (shared footer), never added twice


def test_excerpt_matches_by_name_when_counts_differ_and_falls_back_to_whole_post():
    jobs = [("Haus Of Brands", "Business Analyst")]  # the AI found only one of the three
    assert excerpt(MULTI, jobs, 0, [], []).startswith("3) Company - Haus Of Brands")
    single = "Company - Acme\nRole - AI Engineer"
    assert excerpt(single, [("Acme", "AI Engineer")], 0, [], []) == single


@requires_db
async def test_job_card_gets_only_its_own_part_and_its_resume(db):
    uid = await store.get_or_create_user(db, "cards@x.com")
    ch = Channel(user_id=uid, tg_chat_id=-5, title="c", enabled=True)
    r = Resume(user_id=uid, name="AI Resume v2", text="x", pdf=b"%PDF", filename="r.pdf", is_active=True)
    db.add_all([ch, r])
    await db.flush()
    p = Post(user_id=uid, channel_id=ch.id, tg_message_id=1, text=MULTI, posted_at=datetime.now(UTC), stage="scored")
    db.add(p)
    await db.flush()
    jobs = [Job(user_id=uid, post_id=p.id, idx=i, company=c, role=role, resume_id=r.id)
            for i, (c, role) in enumerate([("iRage", "Software Developer Intern"), ("iRage", "Quantitative Analyst Intern"),
                                           ("Haus Of Brands", "Business Analyst")])]
    db.add_all(jobs)
    await db.commit()
    card = await job_json(db, jobs[1])
    assert "Quantitative" in card["post_text"] and "Software Developer" not in card["post_text"]
    assert card["checked_with"] == "AI Resume v2"
