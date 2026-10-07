"""Resume versions: list (with how many emails each wrote), switch back, delete, and scanned resumes via OCR."""
import pymupdf
import pytest
from sqlalchemy import select

from app.db.models import Resume, ResumeChunk, Send
from app.pipeline import resume
from app.telegram import store
from tests.conftest import requires_db
from tests.test_ocr import screenshot
from tests.test_outbox import master_key, setup, smtp  # noqa: F401 (fixtures)
from tests.test_resume_match import AI_RESUME, make_pdf


@requires_db
async def test_versions_activate_and_delete(db):
    uid = await store.get_or_create_user(db, "a@x.com")
    old = await resume.add_resume(db, uid, "Old", make_pdf(AI_RESUME))
    new = await resume.add_resume(db, uid, "New", make_pdf(AI_RESUME + " Kubernetes."))
    rows = await resume.list_resumes(db, uid)
    assert [(r.name, r.is_active, n) for r, n in rows] == [("New", True, 0), ("Old", False, 0)]
    await resume.activate_resume(db, uid, old.id)
    assert (await resume.active_resume(db, uid)).id == old.id
    with pytest.raises(resume.ActiveResume):
        await resume.delete_resume(db, uid, old.id)
    await resume.delete_resume(db, uid, new.id)
    assert await db.get(Resume, new.id) is None
    assert not (await db.execute(select(ResumeChunk).where(ResumeChunk.resume_id == new.id))).first()


@requires_db
async def test_other_users_resumes_are_out_of_reach(db):
    a = await store.get_or_create_user(db, "a@x.com")
    b = await store.get_or_create_user(db, "b@x.com")
    r = await resume.add_resume(db, a, "Mine", make_pdf(AI_RESUME))
    await resume.add_resume(db, b, "Theirs", make_pdf(AI_RESUME))
    with pytest.raises(resume.ResumeNotFound):
        await resume.activate_resume(db, b, r.id)
    with pytest.raises(resume.ResumeNotFound):
        await resume.delete_resume(db, b, r.id)


@requires_db
async def test_a_resume_a_scheduled_email_will_attach_cannot_be_deleted(db, smtp):
    uid, [job] = await setup(db)  # its resume wrote a draft; schedule that draft, then switch resumes
    from app.mailer import outbox
    from datetime import timedelta

    from tests.test_outbox import NOW
    await outbox.approve(db, uid, job, NOW + timedelta(days=1), now=NOW)
    used = (await db.execute(select(Resume).where(Resume.user_id == uid))).scalar_one()
    await resume.add_resume(db, uid, "Newer", make_pdf(AI_RESUME))
    assert (await db.execute(select(Send).where(Send.user_id == uid))).scalar_one().status == "scheduled"
    with pytest.raises(resume.ResumeInUse):
        await resume.delete_resume(db, uid, used.id)


def test_scanned_resume_is_read_with_ocr():
    doc = pymupdf.open()
    page = doc.new_page()
    lines = ["Chetan Mahajan AI Engineer", "Python PyTorch LangChain RAG FastAPI", "Built BankAssist RAG chatbot",
             "Built LexIQ legal research assistant", "Deployed on AWS EC2 with CI CD pipelines",
             "Chest X-Ray classifier DenseNet121"]
    page.insert_image(page.rect, stream=screenshot(*lines))
    text = resume.pdf_or_ocr_text(doc.tobytes())
    assert "BankAssist" in text and "LangChain" in text


@requires_db
async def test_upload_can_keep_the_current_primary(db):
    uid = await store.get_or_create_user(db, "p@x.com")
    first = await resume.add_resume(db, uid, "First", make_pdf(AI_RESUME), primary=False)
    assert first.is_active  # the first resume is always primary
    second = await resume.add_resume(db, uid, "Second", make_pdf(AI_RESUME), primary=False)
    assert not second.is_active and (await resume.active_resume(db, uid)).id == first.id
    third = await resume.add_resume(db, uid, "Third", make_pdf(AI_RESUME))
    assert (await resume.active_resume(db, uid)).id == third.id


@requires_db
async def test_new_primary_rechecks_recent_jobs_but_not_emailed_or_old_ones(db):
    from datetime import UTC, datetime, timedelta

    from app.db.models import Channel, Job, Post

    uid = await store.get_or_create_user(db, "r@x.com")
    await resume.add_resume(db, uid, "Old", make_pdf(AI_RESUME))
    ch = Channel(user_id=uid, tg_chat_id=-1, title="c", enabled=True)
    db.add(ch)
    await db.flush()
    now = datetime.now(UTC)

    def mk(msg, when, stage, reason=None):
        p = Post(user_id=uid, channel_id=ch.id, tg_message_id=msg, text="x", posted_at=when, stage=stage,
                 skip_reason=reason)
        db.add(p)
        return p

    fresh, emailed, old, weak = (mk(1, now, "scored"), mk(2, now, "scored"),
                                 mk(3, now - timedelta(days=5), "scored"), mk(4, now, "skipped", "low_match"))
    await db.flush()
    jobs = [Job(user_id=uid, post_id=p.id, idx=0, company="A", role="ML", fit_score=80, verdict="APPLY")
            for p in (fresh, emailed, old)]
    db.add_all(jobs)
    await db.flush()
    from app.db.models import SenderAccount

    sender = SenderAccount(user_id=uid, email="me@x.com", provider="gmail", password_enc=b"x")
    db.add(sender)
    await db.flush()
    db.add(Send(user_id=uid, job_id=jobs[1].id, to_email="hr@a.com", status="sent", send_at=now, subject="s",
                body="b", sender_id=sender.id, send_key="k1", test_mode=True))
    await db.commit()

    assert await resume.recheck_recent(db, uid) == 2  # the fresh scored post + the weak-match post
    for j in jobs:
        await db.refresh(j)
    assert [j.fit_score for j in jobs] == [None, 80, 80]
    for p in (fresh, weak, old):
        await db.refresh(p)
    assert (fresh.stage, weak.stage, old.stage) == ("extracted", "new", "scored")
