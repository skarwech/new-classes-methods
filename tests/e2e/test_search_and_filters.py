"""Search and filters in the browser: the counter, the tree and the open folders."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e import helpers as h

pytestmark = pytest.mark.e2e


def test_halasz_finds_two_methods_and_every_folder_is_open(page: Page) -> None:
    h.search(page, "halasz")
    h.expect_counter(page, "2 of 170 methods")
    h.wait_for_tree(page)
    found = h.rows(page)
    assert [item.label for item in found] == [
        "Unknown Rejection (2)",
        "1.1 Discriminative Open Set Recognition (1)",
        "Time-series-specific (1)",
        "Halász et al. (time series) (2023)",
        "1.2 Generative Open Set Recognition (1)",
        "Halász et al. (fake features) (2023)",
    ]
    assert all(item.expanded in (True, None) for item in found)  # no closed folder
    h.settle(page)


def test_candes_finds_one_method(page: Page) -> None:
    h.search(page, "candes")
    h.expect_counter(page, "1 of 170 methods")
    h.wait_for_tree(page)
    assert h.labels(page) == [
        "Pipeline component references (1)",
        "Statistical building blocks (1)",
        "Calibration under shift (1)",
        "Gibbs & Candès (2021)",
    ]


def test_typing_the_accents_works_too(page: Page) -> None:
    h.search(page, "HALÁSZ")
    h.expect_counter(page, "2 of 170 methods")


def test_search_looks_at_authors_and_titles_not_only_names(page: Page) -> None:
    h.search(page, "scheirer")  # 1-vs-Set, W-SVM, PI-SVM and EVM list him as an author
    h.expect_counter(page, "4 of 170 methods")
    h.search(page, "extreme value machine")
    h.expect_counter(page, "1 of 170 methods")


def test_a_search_with_no_match_replaces_the_tree_by_a_message(page: Page) -> None:
    h.search(page, "zzzzqqqq")
    h.expect_counter(page, "0 of 170 methods")
    expect(page.locator(h.TREE_IFRAME)).to_have_count(0)
    expect(page.get_by_text("No methods match the current search")).to_be_visible()
    expect(
        page.get_by_role("button", name="Download filtered rows (CSV)")
    ).to_be_disabled()
    h.settle(page)

    h.search(page, "")  # back to everything: a fresh, collapsed tree
    h.expect_counter(page, "170 of 170 methods")
    h.wait_for_tree(page)
    assert len(h.labels(page)) == 5
    assert all(item.expanded is False for item in h.rows(page))


@pytest.mark.parametrize(
    "text", ["(", "[a-", ".*", "\\", "a|b", "(?i)", "'; DROP", "<b>"]
)
def test_odd_characters_in_the_search_box_do_not_break_the_page(
    page: Page, text: str
) -> None:
    h.search(page, text)
    page.wait_for_timeout(600)
    expect(page.locator('[data-testid="stException"]')).to_have_count(0)
    assert h.counter(page).endswith("of 170 methods")


def test_the_family_filter_keeps_one_family_with_its_sections_open(page: Page) -> None:
    h.choose(page, "Family", "Class Discovery")
    h.expect_counter(page, "31 of 170 methods")
    h.wait_for_tree(page)
    shown = h.labels(page)
    assert shown[:3] == [
        "Class Discovery (31)",
        "2.1 Novel Class Discovery (9)",
        "Transfer clustering (two-stage) (3)",
    ]
    assert not any(label.startswith("Unknown Rejection") for label in shown)
    assert h.open_labels(page)[:3] == shown[:3]  # family, section and type are open
    h.settle(page)


def test_the_code_and_reference_check_filters(page: Page) -> None:
    h.choose(page, "Code availability", "No public code found")
    h.expect_counter(page, "40 of 170 methods")
    h.choose(page, "Reference check", "Incomplete or flagged")
    # both filters together: only rows that are flagged AND have no public code
    page.wait_for_timeout(800)
    count = int(h.counter(page).split(" of ")[0])
    assert 0 < count < 40
    h.wait_for_tree(page)
    assert len(h.rows(page)) >= 3  # at least one family, one section and one method
    h.settle(page)


def test_every_filter_result_has_no_empty_folder(page: Page) -> None:
    """Whatever the filter shows, every folder row that is drawn has a non-zero count."""
    for query in ("open", "stream", "net", "a"):
        h.search(page, query)
        page.wait_for_timeout(700)
        h.wait_for_tree(page)
        folders = [item for item in h.rows(page) if item.is_folder]
        assert folders
        assert not [item.label for item in folders if item.label.endswith("(0)")]
        assert all(item.expanded for item in folders)  # a filter opens every folder


def test_a_long_pasted_search_is_kept_whole(page: Page) -> None:
    pasted = (
        "Learning a Neural-Network-Based Representation for Open Set Recognition "
        "Learning a Neural-Network-Based Representation"
    )
    assert len(pasted) > 100
    h.search(page, pasted)
    h.expect_counter(page, "1 of 170 methods")  # the one title that has all these words
    assert h.search_box(page).input_value() == pasted


def test_punctuation_in_a_pasted_byline_does_not_stop_the_match(page: Page) -> None:
    h.search(page, "Bendale, Boult")
    h.expect_counter(page, "2 of 170 methods")
    h.search(page, "open-set")
    hyphen = h.counter(page)
    h.search(page, "open set")
    h.expect_counter(page, hyphen)  # the same words, the same methods
    assert hyphen != "170 of 170 methods"
