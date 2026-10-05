from types import SimpleNamespace

import pytest

from app.mailer import rules

PROFILE = {"home_city": "Pune", "full_name": "Chetan Mahajan"}


def job(location=None, apply_instructions=None, hr_name=None, work_mode="unknown"):
    return SimpleNamespace(location=location, apply_instructions=apply_instructions, hr_name=hr_name, work_mode=work_mode)


# --- greeting ------------------------------------------------------------------

@pytest.mark.parametrize(("hr_name", "expected"), [
    ("Aditi", "Aditi"), ("aditi akulwar", "Aditi"), ("Ms. Sowmya", "Sowmya"), (None, None), ("", None),
])
def test_hr_first_name(hr_name, expected):
    assert rules.hr_first_name(hr_name) == expected


# --- subject ---------------------------------------------------------------------

def test_home_city_job_gets_city_and_immediate_joiner():
    assert rules.subject_parts(job(location="Pune"), PROFILE, "post") == (None, " | Pune | Immediate Joiner")


def test_other_city_job_gets_no_extras():
    assert rules.subject_parts(job(location="Chennai"), PROFILE, "post") == (None, "")


def test_post_asking_for_immediate_joiners_gets_job_city():
    extras = rules.subject_parts(job(location="Noida"), PROFILE, "Immediate joiners preferred")[1]
    assert extras == " | Noida | Immediate Joiner"


@pytest.mark.parametrize("instructions", [
    "subject: AIML-Intern", 'Use subject line "AIML-Intern"', "Mention subject as AIML-Intern", "Subject - AIML-Intern",
])
def test_required_subject_is_used_exactly(instructions):
    assert rules.subject_parts(job(apply_instructions=instructions), PROFILE, "post")[0] == "AIML-Intern"


def test_job_id_is_added_to_subject():
    extras = rules.subject_parts(job(location="Chennai"), PROFILE, "Job ID: 3095727 · mail hr@x.ai")[1]
    assert extras == " | Job ID 3095727"


# --- closing line location phrase ------------------------------------------------

@pytest.mark.parametrize(("location", "mode", "phrase"), [
    ("Pune", "onsite", "based in Pune"),
    ("Pune, Maharashtra", "hybrid", "based in Pune"),
    ("Chennai", "onsite", "open to relocating to Chennai"),
    ("Delhi NCR / Gurugram", "onsite", "open to relocating to Delhi NCR"),
    ("Bangalore", "remote", "comfortable working remotely"),
    (None, "unknown", "based in Pune"),
])
def test_location_phrase(location, mode, phrase):
    assert rules.location_phrase(job(location=location, work_mode=mode), PROFILE) == phrase
