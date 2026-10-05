"""The approved template must reproduce the 3 real sample emails in the template doc, character for character."""

import pytest

from app.mailer import render
from app.mailer.examples import load as examples
from app.mailer.examples import slots_from


def test_doc_has_the_three_examples():
    assert len(examples()) == 3


@pytest.mark.parametrize("i", [0, 1, 2], ids=["Aptino", "Wentrite", "SmartBridge"])
def test_template_reproduces_real_example_exactly(i):
    email = examples()[i]
    subject, body = render.render(render.default_template(), **slots_from(email))
    assert f"Subject: {subject}\n\n{body}" == email


@pytest.mark.parametrize("i", [0, 1, 2], ids=["Aptino", "Wentrite", "SmartBridge"])
def test_real_examples_fit_the_length_rule(i):
    _, body = render.render(render.default_template(), **slots_from(examples()[i]))
    assert render.MIN_WORDS <= render.word_count(body) <= render.MAX_WORDS


def test_subject_override_replaces_whole_subject():
    s = slots_from(examples()[1]) | {"subject_override": "AIML-Intern | Job ID 3095727"}
    subject, _ = render.render(render.default_template(), **s)
    assert subject == "AIML-Intern | Job ID 3095727"


def test_missing_slot_is_an_error_not_a_blank():
    s = slots_from(examples()[0])
    del s["closing_line"]
    with pytest.raises(Exception, match="closing_line"):
        render.render(render.default_template(), **s)
