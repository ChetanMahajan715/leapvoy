import math

import pymupdf
import pytest
from sqlalchemy import select, update

from app.db.models import Resume, ResumeChunk
from app.pipeline import embed, resume
from app.telegram import store
from tests.conftest import requires_db

AI_RESUME = (
    "Chetan Mahajan. AI Engineer. Built BankAssist, a RAG banking chatbot with LangChain, FAISS, ChromaDB and "
    "Groq LLaMA 3.3. Built LexIQ legal research assistant. Multi-agent chatbot with LangGraph. Python, PyTorch, "
    "scikit-learn, FastAPI. Deployed on AWS EC2 with CI/CD. Chest X-ray classifier with DenseNet121. " * 3
)


def make_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 560, 800), text, fontsize=9)
    return doc.tobytes()


def cos(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


# --- embed ------------------------------------------------------------------

def test_embed_is_384_dim_and_normalized():
    [v] = embed.embed(["AI Engineer with LangChain"])
    assert len(v) == 384
    assert math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-4)


def test_ai_post_is_closer_to_ai_resume_than_accounting_post():
    r, ai, acc = embed.embed([
        AI_RESUME,
        "Hiring AI Engineer: LLMs, RAG, LangChain, Python. Mail hr@acme.ai",
        "Hiring Senior Accountant: Tally, GST filing, bank reconciliation. Mail hr@firm.in",
    ])
    assert cos(r, ai) > cos(r, acc) + 0.05


# --- resume text + chunks ---------------------------------------------------

def test_chunks_overlap_and_cover_text():
    text = " ".join(f"word{i}" for i in range(400))
    chunks = resume.chunk(text, size=300, overlap=50)
    assert len(chunks) > 3 and all(len(c) <= 300 for c in chunks)
    assert chunks[0].split()[-1] in chunks[1]  # overlap
    assert "word399" in chunks[-1] and not chunks[0].startswith(" ")


def test_pdf_to_text_reads_pdf():
    assert "BankAssist" in resume.pdf_to_text(make_pdf(AI_RESUME))


def test_scanned_or_empty_pdf_is_rejected():
    with pytest.raises(resume.ScannedPdfError):
        resume.pdf_to_text(make_pdf("tiny"))


# --- resume links vs profile --------------------------------------------------

PROFILE = {
    "github_url": "https://github.com/ChetanMahajan715",
    "linkedin_url": "https://www.linkedin.com/in/chetanmahajan715/",
    "sender_email": "chetanmahajan715@gmail.com",
}


def pdf_with_links(uris: list[str]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 560, 800), AI_RESUME, fontsize=9)
    for i, uri in enumerate(uris):
        page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(40, 700 + 15 * i, 200, 712 + 15 * i), "uri": uri})
    return doc.tobytes()


def test_pdf_links_reads_clickable_links():
    pdf = pdf_with_links(["https://github.com/abc", "mailto:me@x.com"])
    assert resume.pdf_links(pdf) == ["https://github.com/abc", "mailto:me@x.com"]


def test_old_resume_links_are_flagged():
    old = ["https://linkedin.com/in/chettanmahajan", "https://github.com/chettanmahajan", "mailto:chettanmahajan@gmail.com",
           "https://github.com/chettanmahajan/BankAssist-Chatbot"]  # repo links: same account → one warning
    warnings = resume.link_mismatches(old, PROFILE)
    assert len(warnings) == 3
    assert any("github.com/chettanmahajan" in w and "github.com/ChetanMahajan715" in w for w in warnings)


def test_matching_links_give_no_warnings():
    new = ["https://github.com/chetanmahajan715/", "https://www.linkedin.com/in/ChetanMahajan715", "mailto:chetanmahajan715@gmail.com"]
    assert resume.link_mismatches(new, PROFILE) == []


# --- add_resume + match_score (real DB) --------------------------------------

@requires_db
async def test_add_resume_stores_chunks_with_model_and_lib(db):
    uid = await store.get_or_create_user(db, "a@x.com")
    r = await resume.add_resume(db, uid, "AI Engineer", make_pdf(AI_RESUME))
    chunks = (await db.execute(select(ResumeChunk).where(ResumeChunk.resume_id == r.id))).scalars().all()
    assert chunks and {(c.embed_model, c.embed_lib) for c in chunks} == {(embed.MODEL, embed.LIB)}


@requires_db
async def test_add_resume_keeps_the_pdf_for_attaching(db):
    uid = await store.get_or_create_user(db, "a@x.com")
    pdf = make_pdf(AI_RESUME)
    r = await resume.add_resume(db, uid, "AI", pdf, filename="Chetan Mahajan Resume.pdf")
    assert (r.pdf, r.filename) == (pdf, "Chetan Mahajan Resume.pdf")


@requires_db
async def test_new_resume_becomes_active_and_old_one_is_kept(db):
    uid = await store.get_or_create_user(db, "a@x.com")
    old = await resume.add_resume(db, uid, "v1", make_pdf(AI_RESUME))
    new = await resume.add_resume(db, uid, "v2", make_pdf(AI_RESUME + " Kubernetes."))
    rows = {r.name: r.is_active for r in (await db.execute(select(Resume))).scalars()}
    assert rows == {"v1": False, "v2": True} and old.id != new.id


@requires_db
async def test_match_score_ranks_ai_post_higher(db):
    uid = await store.get_or_create_user(db, "a@x.com")
    await resume.add_resume(db, uid, "AI", make_pdf(AI_RESUME))
    ai = await resume.match_score(db, uid, "Hiring GenAI Engineer: RAG, LangChain, LLM agents, Python")
    acc = await resume.match_score(db, uid, "Hiring Accountant: Tally, GST, payroll, audits")
    assert ai > acc


@requires_db
async def test_match_score_is_none_without_resume_and_never_uses_other_users(db):
    a = await store.get_or_create_user(db, "a@x.com")
    b = await store.get_or_create_user(db, "b@x.com")
    await resume.add_resume(db, a, "AI", make_pdf(AI_RESUME))
    assert await resume.match_score(db, b, "AI Engineer") is None


@requires_db
async def test_chunks_from_old_model_are_reembedded(db):
    uid = await store.get_or_create_user(db, "a@x.com")
    await resume.add_resume(db, uid, "AI", make_pdf(AI_RESUME))
    await db.execute(update(ResumeChunk).values(embed_model="old-model", embedding=[0.0] * 383 + [1.0]))
    await db.commit()
    assert await resume.match_score(db, uid, "AI Engineer LangChain") > 0.5  # would be ~0 with stale vectors
    models = set((await db.execute(select(ResumeChunk.embed_model))).scalars())
    assert models == {embed.MODEL}
