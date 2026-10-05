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
