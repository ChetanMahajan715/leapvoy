import pytest

from app.llm.schemas import FitCheck
from app.pipeline.rules import apply_rules


def fit(score=82, verdict="STRONG MATCH", family="target", years=None, batch_ok=True, flags=None):
    return FitCheck(
        score=score, verdict=verdict, role_family=family, min_years_required=years, batch_eligible=batch_ok,
        rows=[], matched_skills=[], gaps=[], flags=flags or [],
    )


def test_target_role_for_fresher_keeps_ai_verdict():
    out = apply_rules(fit())
    assert (out.score, out.verdict) == (82, "STRONG MATCH")


@pytest.mark.parametrize("years", [None, 0, 1])
def test_zero_to_one_years_or_1_to_3_range_is_fine(years):
    # "1-3 years" → min 1 → apply normally (user got replies to such posts)
    assert apply_rules(fit(years=years)).verdict == "STRONG MATCH"


def test_unrelated_role_is_skipped():
    out = apply_rules(fit(score=60, verdict="APPLY", family="unrelated"))  # e.g. Product / Program Management
    assert out.verdict == "SKIP" and out.score <= 39


def test_adjacent_role_is_at_most_maybe():
    out = apply_rules(fit(score=78, verdict="STRONG MATCH", family="adjacent"))  # e.g. backend Python dev
    assert out.verdict == "MAYBE" and out.score <= 54


@pytest.mark.parametrize("years", [2, 3, 4])
def test_two_to_four_years_minimum_is_at_most_maybe(years):
    assert apply_rules(fit(years=years)).verdict == "MAYBE"


@pytest.mark.parametrize("years", [5, 8, 10])
def test_five_plus_years_is_skipped(years):
    assert apply_rules(fit(years=years)).verdict == "SKIP"


def test_batch_not_eligible_is_maybe_with_flag():
    out = apply_rules(fit(batch_ok=False))
    assert out.verdict == "MAYBE" and "batch not eligible" in out.flags


def test_rules_never_upgrade_a_verdict():
    assert apply_rules(fit(score=30, verdict="SKIP", family="adjacent")).verdict == "SKIP"
    assert apply_rules(fit(score=45, verdict="MAYBE")).verdict == "MAYBE"


@pytest.mark.parametrize("title", [
    "QA Intern", "Business Analyst - BI", "Investment Analyst", "Associate Program Manager (Analyst)",
    "Product Support - Intern", "Trainee – Talent Acquisition", "Industrial Design Intern", "Sales Executive",
])
def test_unrelated_titles_are_skipped_even_if_ai_says_adjacent(title):
    assert apply_rules(fit(score=60, verdict="APPLY", family="adjacent"), role=title).verdict == "SKIP"


@pytest.mark.parametrize("title", ["AI/ML Engineer", "Forward Deployed Engineer", "AI Product Engineer Intern",
                                   "Machine Learning QA Engineer", "Data Scientist"])
def test_titles_with_ai_words_are_left_to_the_ai(title):
    assert apply_rules(fit(), role=title).verdict == "STRONG MATCH"
