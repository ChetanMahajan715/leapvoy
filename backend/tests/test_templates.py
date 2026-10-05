"""Editable email templates: plain text with {tags}, versions per user, safe (no template code), same output as the
approved template when unchanged."""
import pytest
from sqlalchemy import select

from app.db.models import Draft
from app.mailer import drafts, templates
from app.mailer.render import default_template, render
from app.telegram import store
from tests.conftest import requires_db

PROFILE = {"full_name": "Chetan Mahajan", "phone": "9000000000", "linkedin_url": "https://linkedin.com/in/c",
           "github_url": "https://github.com/c"}
BULLETS = [{"label": "RAG", "proof": "Built BankAssist."}, {"label": "Agents", "proof": "Built LexIQ."},
           {"label": "Deploy", "proof": "AWS EC2."}]


def values(**kw):
    return {"role": "AI Engineer", "company": "Acme Inc.", "hr_first_name": None, "subject_override": None,
            "subject_extras": "", "profile": PROFILE, "opening_line": "Opening.", "fit_bullets": BULLETS,
            "closing_line": "Closing.", **kw}


@pytest.mark.parametrize("kw", [{}, {"hr_first_name": "Aditi"}, {"subject_override": "ML Intern - Chetan"},
                                {"subject_extras": " | 2025 batch"}])
def test_default_text_renders_exactly_like_the_approved_template(kw):
    assert render(templates.to_jinja(templates.DEFAULT_TEXT), **values(**kw)) == render(default_template(), **values(**kw))


def test_a_custom_template_uses_the_tags():
    text = ("Subject: {role} application from {name}\n\nHi {hr_name},\n\nI'd love to join {company} as {role}. "
            "{opening_line}\n\n{fit_bullets}\n\n{closing_line}\n\nThanks,\n{name} | {phone} | {github}")
    subject, body = render(templates.to_jinja(text), **values())
    assert subject == "AI Engineer application from Chetan Mahajan"
    assert body.startswith("Hi Hiring Team,\n\nI'd love to join Acme Inc as AI Engineer. Opening.")
    assert "- RAG: Built BankAssist.\n- Agents: Built LexIQ.\n- Deploy: AWS EC2.\n\nClosing." in body
    # a subject the post demands still wins
    assert render(templates.to_jinja(text), **values(subject_override="Exact Subject"))[0] == "Exact Subject"


@pytest.mark.parametrize(("text", "says"), [
    ("Hello {role}", "Subject:"),
    ("Subject: x\n\n{opening_line}\n{fit_bullets}\n{closing_line} {{ 7*7 }}", "only tags"),
    ("Subject: x\n\n{opening_line}\n{fit_bullets}\n{closing_line} {% raw %}", "only tags"),
    ("Subject: x\n\n{opening_line}\n{fit_bullets}\n{closing_line} {salary}", "{salary}"),
    ("Subject: x\n\n{opening_line}\n{closing_line}", "{fit_bullets}"),
    ("Subject: x\n\n{opening_line}\nPoints: {fit_bullets}\n{closing_line}", "own line"),
    ("Subject: x\n\n{opening_line}\n{opening_line}\n{fit_bullets}\n{closing_line}", "once"),
])
def test_unsafe_or_broken_templates_are_refused_with_a_clear_reason(text, says):
    with pytest.raises(templates.TemplateError) as e:
        templates.to_jinja(text)
    assert says in str(e.value)


@requires_db
async def test_versions_and_back_to_default(db):
    uid = await store.get_or_create_user(db, "a@x.com")
    assert (await templates.active(db, uid)).name == "default-v1"
    text = templates.DEFAULT_TEXT.replace("Best regards,", "Warm regards,")
    v1 = await templates.save(db, uid, text)
    v2 = await templates.save(db, uid, text.replace("Warm", "Kind"))
    t = await templates.active(db, uid)
    assert (t.name, v2.version, v1.version) == ("custom-v2", 2, 1) and "Kind regards," in t.text
    await templates.activate(db, uid, v1.id)
    assert (await templates.active(db, uid)).name == "custom-v1"
    await templates.use_default(db, uid)
    assert (await templates.active(db, uid)).name == "default-v1"
    other = await store.get_or_create_user(db, "b@x.com")
    with pytest.raises(templates.TemplateNotFound):
        await templates.activate(db, other, v1.id)


@requires_db
async def test_changing_the_template_makes_written_emails_outdated(db, monkeypatch):
    from tests.test_drafts import GOOD, make_job

    async def fake(tier, messages, response_model, **kw):
        return GOOD

    monkeypatch.setattr(drafts, "structured", fake)
    uid, job_id = await make_job(db)
    d = await drafts.write_draft(db, uid, job_id)
    assert d.template_name == "default-v1" and await drafts.outdated_reason(db, d) is None
    await templates.save(db, uid, templates.DEFAULT_TEXT.replace("Best regards,", "Warm regards,"))
    assert await drafts.outdated_reason(db, d) == "template"
    d = await drafts.write_draft(db, uid, job_id)
    assert d.template_name == "custom-v1" and "Warm regards," in d.body and d.status == "draft"
    assert (await db.execute(select(Draft))).scalar_one().issues == []
