from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.accounts import profile
from app.db.models import Channel, Draft, Job, Post, Resume
from app.llm.schemas import EmailSlots, FitBullet
from app.mailer import drafts
from app.telegram import store
from tests.conftest import requires_db

pytestmark = requires_db
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
RESUME = (
    "Chetan Mahajan. AI/ML Engineer (LLMs, RAG, Deep Learning). BankAssist: RAG banking chatbot with LangChain, FAISS, Groq LLaMA 3.3, FastAPI, Streamlit; "
    "850+ indexed documents; deployed on AWS EC2 with CI/CD using GitHub Actions. LexIQ: legal research assistant "
    "with ChromaDB and Sentence Transformers. Chest X-ray classifier with DenseNet121 and PyTorch, 97.8% accuracy. "
    "Data Science Intern at Vcity Soft Solutions: ML pipelines with Python, XGBoost, LightGBM; 7% improvement."
)
PROFILE = {
    "full_name": "Chetan Mahajan", "phone": "9000000000", "home_city": "Pune",
    "github_url": "https://github.com/ChetanMahajan715", "linkedin_url": "https://www.linkedin.com/in/chetanmahajan715/",
    "education": "2026 batch BCA (Cloud Computing) graduate", "availability": "immediately available",
}

GOOD = EmailSlots(
    opening_line="The focus on LLMs, RAG, and Python maps closely to my background.",
    fit_bullets=[
        FitBullet(label="LLMs and RAG", proof="Built BankAssist, a RAG banking chatbot using LangChain, FAISS, and Groq "
                  "LLaMA 3.3 over 850+ indexed documents, served through FastAPI and Streamlit."),
        FitBullet(label="Python and ML", proof="Built ML pipelines in Python with XGBoost and LightGBM during my Data "
                  "Science internship at Vcity Soft Solutions, reaching a 7% improvement over baseline."),
        FitBullet(label="Deep Learning", proof="Built a chest X-ray classifier with DenseNet121 and PyTorch reaching "
                  "97.8% accuracy, and LexIQ, a legal research assistant using ChromaDB and Sentence Transformers."),
        FitBullet(label="Deployment", proof="Deployed BankAssist on AWS EC2 with a CI/CD pipeline using GitHub Actions."),
    ],
    closing_line="I am a 2026 batch BCA (Cloud Computing) graduate, immediately available, and open to relocating to Mumbai.",
)
INVENTED = GOOD.model_copy(update={"fit_bullets": [
    *GOOD.fit_bullets[:3], FitBullet(label="Deployment", proof="Deployed models with Kubernetes and Docker on AWS EC2."),
]})
TOO_SHORT = GOOD.model_copy(update={"fit_bullets": GOOD.fit_bullets[:3], "opening_line": "It fits.",
                                    "closing_line": "I am available."})


class FakeLLM:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[list[dict]] = []

    async def __call__(self, tier, messages, response_model, **kw):
        assert response_model is EmailSlots and tier == "large"
        self.calls.append(list(messages))
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


@pytest.fixture
def llm(monkeypatch):
    def use(*answers):
        fake = FakeLLM(*answers)
        monkeypatch.setattr(drafts, "structured", fake)
        return fake
    return use


async def make_job(db, email="a@x.com", apply_method="email", verdict="STRONG MATCH"):
    uid = await store.get_or_create_user(db, email)
    await profile.set_profile(db, uid, PROFILE)
    db.add(Resume(user_id=uid, name="AI", text=RESUME, pdf=b"%PDF-1.4 fake", filename="cv.pdf", is_active=True))
    ch = Channel(user_id=uid, tg_chat_id=-1001, title="Jobs", enabled=True)
    db.add(ch)
    await db.flush()
    post = Post(user_id=uid, channel_id=ch.id, tg_message_id=1, posted_at=NOW, stage="scored",
                text="Company - Allvest | Role - AI Engineer | Location - Mumbai | Skills: LLMs, RAG, Python | mail hr@allvest.co")
    db.add(post)
    await db.flush()
    job = Job(user_id=uid, post_id=post.id, idx=0, company="Allvest Securities", role="AI Engineer",
              hr_emails=["hr@allvest.co"] if apply_method == "email" else [], apply_method=apply_method,
              apply_links=[] if apply_method == "email" else ["https://forms.gle/x"], location="Mumbai",
              work_mode="onsite", must_have_skills=["LLMs", "RAG", "Python"], fit_score=81, verdict=verdict,
              fit_rows=[{"requirement": "LLMs", "fit": "Strong", "note": "BankAssist"}])
    db.add(job)
    await db.commit()
    return uid, job.id


async def test_clean_draft_is_saved_from_template(db, llm):
    fake = llm(GOOD)
    uid, job_id = await make_job(db)
    d = await drafts.write_draft(db, uid, job_id)
    assert (d.status, d.issues, d.to_emails) == ("draft", [], ["hr@allvest.co"])
    assert d.subject == "Application for AI Engineer - Chetan Mahajan"
    assert d.body.startswith("Dear Hiring Team,\n\nI am writing to apply for the AI Engineer role at Allvest Securities.")
    assert "GitHub: https://github.com/ChetanMahajan715" in d.body and d.body.endswith("Chetan Mahajan\n9000000000")
    assert d.resume_id == (await db.execute(select(Resume.id).where(Resume.is_active))).scalar_one()
    assert len(fake.calls) == 1


async def test_an_invented_bullet_is_dropped_without_another_ai_call(db, llm):
    """3 sound bullets remain, so the invented one just goes (faster, saves free AI quota)."""
    fake = llm(INVENTED)
    uid, job_id = await make_job(db)
    d = await drafts.write_draft(db, uid, job_id)
    assert (d.status, d.issues) == ("draft", []) and "Kubernetes" not in d.body and len(fake.calls) == 1


THREE_ONE_INVENTED = GOOD.model_copy(update={"fit_bullets": [
    *GOOD.fit_bullets[:2], FitBullet(label="Deployment", proof="Deployed models with Kubernetes and Docker on AWS EC2."),
]})


async def test_too_few_sound_bullets_are_sent_back_with_the_reason(db, llm):
    fake = llm(THREE_ONE_INVENTED, GOOD)
    uid, job_id = await make_job(db)
    d = await drafts.write_draft(db, uid, job_id)
    assert (d.status, d.issues) == ("draft", [])
    assert len(fake.calls) == 2 and "Kubernetes" in fake.calls[1][-1]["content"]


async def test_still_invented_after_rewrites_needs_review(db, llm):
    fake = llm(THREE_ONE_INVENTED)
    uid, job_id = await make_job(db)
    d = await drafts.write_draft(db, uid, job_id)
    assert d.status == "needs_review" and "not in your resume: Kubernetes, Docker" in d.issues[0]
    assert len(fake.calls) == drafts.MAX_ATTEMPTS


async def test_too_short_email_is_rewritten(db, llm):
    fake = llm(TOO_SHORT, GOOD)
    uid, job_id = await make_job(db)
    d = await drafts.write_draft(db, uid, job_id)
    assert d.status == "draft" and "words" in fake.calls[1][-1]["content"]


async def test_link_jobs_get_no_email(db, llm):
    llm(GOOD)
    uid, job_id = await make_job(db, apply_method="link")
    with pytest.raises(drafts.NotAnEmailJob):
        await drafts.write_draft(db, uid, job_id)


async def test_cannot_draft_another_users_job(db, llm):
    llm(GOOD)
    _, job_id = await make_job(db, "a@x.com")
    other = await store.get_or_create_user(db, "b@x.com")
    with pytest.raises(drafts.JobNotFound):
        await drafts.write_draft(db, other, job_id)


async def test_redrafting_replaces_the_old_draft(db, llm):
    llm(GOOD)
    uid, job_id = await make_job(db)
    await drafts.write_draft(db, uid, job_id)
    await drafts.write_draft(db, uid, job_id)
    assert (await db.execute(select(func.count()).select_from(Draft))).scalar_one() == 1


async def test_draft_is_outdated_after_a_new_resume(db, llm):
    llm(GOOD)
    uid, job_id = await make_job(db)
    d = await drafts.write_draft(db, uid, job_id)
    assert not await drafts.is_outdated(db, d)
    old = (await db.execute(select(Resume).where(Resume.is_active))).scalar_one()
    old.is_active = False
    db.add(Resume(user_id=uid, name="v2", text=RESUME, is_active=True))
    await db.commit()
    assert await drafts.is_outdated(db, d)


async def test_email_jobs_to_draft_skips_skip_and_link_jobs(db, llm):
    llm(GOOD)
    uid, good = await make_job(db)
    job = await db.get(Job, good)
    db.add(Job(user_id=uid, post_id=job.post_id, idx=1, company="X", role="QA", hr_emails=["q@x.ai"], fit_score=20,
               verdict="SKIP"))
    db.add(Job(user_id=uid, post_id=job.post_id, idx=2, company="Y", role="AI", hr_emails=[], apply_method="link",
               apply_links=["https://forms.gle/y"], fit_score=80, verdict="APPLY"))
    await db.commit()
    assert await drafts.email_jobs_needing_drafts(db, uid, NOW.replace(hour=0), NOW.replace(hour=23)) == [good]
    await drafts.write_draft(db, uid, good)
    assert await drafts.email_jobs_needing_drafts(db, uid, NOW.replace(hour=0), NOW.replace(hour=23)) == []


def test_special_characters_are_made_plain():
    s = drafts.plain(GOOD.model_copy(update={"opening_line": "The focus on full‑stack and LLM‐based apps maps closely to my background."}))
    assert s.opening_line == "The focus on full-stack and LLM-based apps maps closely to my background."


def test_em_dashes_never_reach_an_email():
    em = chr(0x2014)
    s = drafts.plain(GOOD.model_copy(update={"opening_line": f"Your AI team{em}built on RAG {em} matches my work."}))
    assert em not in s.model_dump_json() and s.opening_line == "Your AI team-built on RAG, matches my work."


def test_style_examples_drop_claims_the_current_resume_does_not_back():
    ex = drafts.style_examples(  # a resume with BankAssist and LexIQ in its own words, but no LangGraph project
        "Built BankAssist, a full-stack RAG banking chatbot, and LexIQ, a legal research assistant, using LangChain, "
        "FAISS, ChromaDB, Groq LLaMA 3.3, and Hugging Face Transformers, both deployed end-to-end. "
        "Python AWS EC2 CI/CD S3 CloudWatch 2026 BCA Pune Vcity Soft Solutions")
    assert "LangGraph" not in ex  # the multi-agent project isn't on this resume
    assert "BankAssist" in ex  # backed bullets stay as style guidance


def test_bullets_from_how_to_apply_or_invented_wording_are_sent_back():
    """User, 9 Oct: no 'Send resume: …' bullets and no claims the resume doesn't say."""
    from app.mailer.guard import instruction_labels, ungrounded_proofs

    assert instruction_labels([{"label": "Send resume", "proof": ""}, {"label": "RAG and LangChain", "proof": ""}]) == [
        "Send resume"]
    real = {"label": "Computer Vision", "proof": "Chest X-ray classifier with DenseNet121 and PyTorch, 97.8% accuracy."}
    invented = {"label": "Leadership", "proof": "Led a team of five engineers to ship a recommender used by thousands."}
    assert ungrounded_proofs([real, invented], RESUME) == ["Leadership"]


def test_closing_line_is_fixed_text_from_the_profile():
    from types import SimpleNamespace

    from app.mailer.rules import closing_line

    job = SimpleNamespace(work_mode="onsite", location="Pune")
    p = PROFILE | {"education": "BCA (Cloud Computing & System Administration)", "availability": "Immediate Joiner"}
    assert closing_line(job, p) == ("I am a BCA (Cloud Computing and System Administration) graduate, "
                                    "immediately available, and based in Pune.")
    away = SimpleNamespace(work_mode="onsite", location="Noida, Uttar Pradesh")
    assert closing_line(away, PROFILE).endswith("immediately available, and open to relocating to Noida.")


async def test_missing_profile_fields_are_named_before_any_ai_call(db, llm):
    fake = llm(GOOD)
    uid, job_id = await make_job(db)
    await profile.set_profile(db, uid, {k: v for k, v in PROFILE.items() if k != "github_url"})
    with pytest.raises(drafts.ProfileIncomplete) as e:
        await drafts.write_draft(db, uid, job_id)
    assert e.value.missing == ["GitHub link"] and fake.calls == []


def test_a_fact_stays_with_its_own_project():
    """Seen 9 Oct: 'Leapvoy ... served via Nginx on AWS EC2' when EC2 and Nginx belong to BankAssist."""
    from app.mailer.guard import misattributed

    resume = ("Projects\nLeapvoy: AI Job-Outreach Agent | FastAPI, LangGraph, Docker\n"
              "• Delivered a FastAPI backend, deployed with Docker Compose.\n"
              "BankAssist: Banking RAG Chatbot | FAISS, AWS EC2\n• Deployed to AWS EC2 behind an Nginx reverse proxy.\n"
              "Education\nBCA")
    mixed = {"label": "Deployment", "proof": "Deployed Leapvoy with Docker Compose behind Nginx on AWS EC2."}
    right = {"label": "Cloud", "proof": "Deployed BankAssist to AWS EC2 behind Nginx, and Leapvoy with Docker Compose."}
    assert misattributed([mixed, right], resume) == ["Deployment"]


def test_labels_get_title_case_but_tool_names_keep_their_spelling():
    resume = "Databases and Vector Search: PostgreSQL, pgvector, FAISS\nBuilt data pipelines for deployment."
    assert drafts._title("vector databases and pgvector", resume) == "Vector Databases and pgvector"
    assert drafts._title("data pipelines and deployment", resume) == "Data Pipelines and Deployment"
    assert drafts._title("RAG and LangChain", resume) == "RAG and LangChain"
