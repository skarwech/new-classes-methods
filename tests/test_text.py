"""The fixed wording on the page."""

from __future__ import annotations

import re

import pytest

from explorer import text
from explorer.constants import CHECK_LABELS, CODE_LABELS
from tests.wording import WORKING_WORDING

pytestmark = pytest.mark.unit

EMOJI_OR_PICTOGRAPH = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿←-⇿️‍]")


def all_visible_strings() -> list[str]:
    constants = [
        value
        for name, value in vars(text).items()
        if name.isupper() and isinstance(value, str)
    ]
    return [*constants, text.description(170), text.count_text(2, 170)]


def test_there_is_text_to_check() -> None:
    assert len(all_visible_strings()) >= 10


def test_no_working_wording_is_shown() -> None:
    for value in all_visible_strings():
        assert not WORKING_WORDING.search(value), value[:60]


def test_no_emoji_or_pictographs_are_shown() -> None:
    for value in all_visible_strings():
        assert not EMOJI_OR_PICTOGRAPH.search(value), value[:60]


def test_description_has_two_lines_and_the_method_count() -> None:
    lines = text.description(170).split("  \n")
    assert len(lines) == 2
    assert "170 methods" in lines[0]


def test_count_text() -> None:
    assert text.count_text(2, 170) == "2 of 170 methods"
    assert text.count_text(0, 170) == "0 of 170 methods"


def test_how_to_read_explains_every_code_label_and_reference_check() -> None:
    for label in (*CODE_LABELS.values(), *CHECK_LABELS.values()):
        assert label in text.HOW_TO_READ, label


def test_how_to_read_warns_that_missing_code_is_not_proof_and_that_some_papers_have_no_link() -> (
    None
):
    lowered = text.HOW_TO_READ.casefold()
    assert "not proof that none exists" in lowered
    assert "no paper link" in lowered or "without a paper link" in lowered


def test_paradigm_names_are_spelled_out() -> None:
    for name in (
        "Unknown Rejection",
        "Class Discovery",
        "Model Integration",
        "Stream Adaptation",
    ):
        assert name in text.HOW_TO_READ


def test_how_to_read_explains_the_also_line() -> None:
    assert "Also:" in text.HOW_TO_READ


def test_the_description_tells_a_phone_visitor_where_the_sidebar_is() -> None:
    assert "sidebar" in text.description(170)
    assert "phone" in text.description(170)
