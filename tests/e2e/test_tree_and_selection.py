"""The tree and the selection, in a real browser with the real tree component.

In every state the highlighted row, the card and the ``?m=`` address must agree, and the
page must settle (the script run count stops growing) after each interaction.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e import helpers as h

pytestmark = pytest.mark.e2e

FAMILIES = [
    "Unknown Rejection (63)",
    "Class Discovery (31)",
    "Model Integration (23)",
    "Stream Adaptation (43)",
    "Pipeline component references (10)",
]
SECTION_1_1 = "1.1 Discriminative Open Set Recognition (19)"
EXTREME_VALUE = "Extreme-value calibrated (2)"
OPENMAX = "OpenMax (2016)"


def open_openmax_path(page: Page) -> None:
    h.wait_for_tree(page)
    h.click_row(page, FAMILIES[0])
    h.click_row(page, SECTION_1_1)
    h.click_row(page, EXTREME_VALUE)


def test_first_screen_shows_five_collapsed_families_and_the_how_to_read_card(
    page: Page,
) -> None:
    assert h.labels(page) == FAMILIES
    assert all(item.expanded is False for item in h.rows(page))
    assert h.selected_labels(page) == []
    h.expect_counter(page, "170 of 170 methods")
    h.expect_card(page, None)
    runs = h.settle(page)
    assert runs in (None, 1)  # one run on arrival, nothing after it


def test_a_folder_opens_and_closes_on_click_without_rerunning_the_script(
    page: Page,
) -> None:
    h.wait_for_tree(page)
    before = h.settle(page)
    h.click_row(page, FAMILIES[0])
    assert h.labels(page)[:5] == [
        FAMILIES[0],
        SECTION_1_1,
        "1.2 Generative Open Set Recognition (9)",
        "1.3 Out-of-Distribution Detection (22)",
        "1.4 One-Class Novelty / Anomaly Detection (13)",
    ]
    assert h.open_labels(page) == [FAMILIES[0]]
    h.click_row(page, FAMILIES[0])
    assert h.labels(page) == FAMILIES
    assert h.settle(page) == before
    assert h.selected_labels(page) == []  # opening a folder never selects it


def test_clicking_a_method_updates_highlight_card_and_address_and_settles(
    page: Page,
) -> None:
    open_openmax_path(page)
    before = h.settle(page)
    h.click_row(page, OPENMAX)
    h.expect_card(page, "OpenMax")
    assert h.selected_labels(page) == [OPENMAX]
    assert h.address_param(page) == "4"
    after = h.settle(page)
    if before is not None:
        assert after - before == 1, "one click must cause exactly one script run"


def test_quick_successive_clicks_end_in_a_consistent_state(page: Page) -> None:
    """Eight rounds of four clicks with no pause, alternating the last click.

    The address once ended up behind the selection here in about a third of the rounds,
    because it was compared with the browser's address instead of what was last sent.
    The first round warms the server up: a cold server answers too slowly to show it.
    """
    open_openmax_path(page)
    h.throttle_cpu(page, 2)
    for number in range(8):
        order = (OPENMAX, "EVM (2018)", OPENMAX, "EVM (2018)")
        if number % 2:
            order = tuple(reversed(order))
        for label in order:
            h.click_row(page, label)
        h.settle(page, quiet_ms=1_000, give_up_ms=30_000)
        last = order[-1]
        heading, expected_id = ("OpenMax", "4") if last == OPENMAX else ("EVM", "5")
        h.expect_card(page, heading)
        assert h.selected_labels(page) == [last], f"round {number}"
        assert h.address_param(page) == expected_id, f"round {number}"


def test_a_selection_survives_an_unrelated_rerun_and_keeps_the_open_folders(
    page: Page,
) -> None:
    open_openmax_path(page)
    h.click_row(page, OPENMAX)
    h.expect_card(page, "OpenMax")
    h.click_row(page, FAMILIES[1])  # open a second family by hand
    page.get_by_text("How to read").first.click()  # toggling the expander is no rerun
    h.settle(page)
    assert h.selected_labels(page) == [OPENMAX]
    assert FAMILIES[0] in h.open_labels(page)
    assert FAMILIES[1] in h.open_labels(page)


# --- the four states the selection can be in -----------------------------------------


def test_state_after_a_click_then_filtered_out_then_filter_cleared(page: Page) -> None:
    open_openmax_path(page)
    h.click_row(page, OPENMAX)
    h.expect_card(page, "OpenMax")

    h.search(page, "halasz")  # OpenMax is not among the matches
    h.expect_counter(page, "2 of 170 methods")
    h.wait_for_tree(page)
    assert "Halász et al. (time series) (2023)" in h.labels(page)
    assert h.selected_labels(page) == []  # nothing highlighted ...
    h.expect_card(page, None)  # ... the card falls back to the how-to-read text ...
    assert h.address_param(page) == "4"  # ... and the address still remembers it
    h.settle(page)

    h.search(page, "")  # clear the filter: the tree is mounted afresh
    h.expect_counter(page, "170 of 170 methods")
    h.expect_card(page, "OpenMax")
    assert h.selected_labels(page) == [OPENMAX]
    assert h.open_labels(page) == [FAMILIES[0], SECTION_1_1, EXTREME_VALUE]
    assert h.address_param(page) == "4"
    h.settle(page)


def test_a_selection_that_stays_visible_is_highlighted_after_the_filter_changes(
    page: Page,
) -> None:
    h.search(page, "halasz")
    h.expect_counter(page, "2 of 170 methods")
    h.click_row(page, "Halász et al. (time series) (2023)")
    h.expect_card(page, "Halász et al. (time series)")
    h.settle(page)

    h.search(page, "halasz time")  # a different filter that still contains it
    h.expect_counter(page, "1 of 170 methods")
    h.wait_for_tree(page)
    assert h.selected_labels(page) == ["Halász et al. (time series) (2023)"]
    h.expect_card(page, "Halász et al. (time series)")
    h.settle(page)

    h.search(page, "")
    h.expect_counter(page, "170 of 170 methods")
    assert h.selected_labels(page) == ["Halász et al. (time series) (2023)"]
    assert h.address_param(page) == "N3"
    h.settle(page)


def test_cold_deep_link_opens_only_the_ancestors_and_highlights_the_method(
    open_at,
) -> None:
    page = open_at("?m=4")
    h.wait_for_tree(page)
    assert h.selected_labels(page) == [OPENMAX]
    assert h.open_labels(page) == [FAMILIES[0], SECTION_1_1, EXTREME_VALUE]
    assert FAMILIES[1] in h.labels(page)  # the other families are there, collapsed
    h.expect_card(page, "OpenMax")
    assert h.address_param(page) == "4"
    h.settle(page)


def test_deep_link_to_a_method_that_has_no_type_folder(open_at) -> None:
    page = open_at("?m=N4")
    h.wait_for_tree(page)
    assert h.selected_labels(page) == ["Halász et al. (fake features) (2023)"]
    assert h.open_labels(page) == [
        FAMILIES[0],
        "1.2 Generative Open Set Recognition (9)",
    ]
    h.expect_card(page, "Halász et al. (fake features)")
    h.settle(page)


def test_a_deep_link_keeps_other_address_parameters(open_at) -> None:
    page = open_at("?m=4&other=keep")
    h.wait_for_tree(page)
    h.expect_card(page, "OpenMax")
    page.wait_for_timeout(500)
    assert h.address_param(page, "other") == "keep"
    assert h.address_param(page, "m") == "4"


@pytest.mark.parametrize(
    "bad",
    ["zzz", "n1", "%3Cscript%3Ealert(1)%3C%2Fscript%3E", "family%3AUnknown+Rejection"],
)
def test_a_bad_deep_link_is_ignored_and_removed_from_the_address(
    open_at, bad: str
) -> None:
    page = open_at(f"?m={bad}")
    h.wait_for_tree(page)
    assert h.labels(page) == FAMILIES
    assert h.selected_labels(page) == []
    h.expect_card(page, None)
    page.wait_for_timeout(800)
    assert h.address_param(page) is None
    h.settle(page)


def test_a_click_that_reaches_the_old_tree_after_typing_still_shows_in_the_new_one(
    page: Page,
) -> None:
    """Type a search term without Enter, then press a row of the tree that is about to be
    replaced. The click was remembered but the new tree did not show it (reviewers saw
    this every time, with the mouse held 20 to 30 ms).

    The 25 ms press is tuned to that window: much longer and the new tree arrives before
    the mouse is released, so no click happens; on a very slow machine it may need a
    shorter press."""
    h.wait_for_tree(page)
    h.click_row(page, FAMILIES[1])
    h.click_row(page, "2.2 Generalized Category Discovery (13)")
    target = h.row(page, "GCD (2022)")
    box = target.bounding_box()
    assert box is not None
    h.search_box(page).fill("gcd")  # no Enter: the click below is what commits it
    page.mouse.move(box["x"] + 40, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.wait_for_timeout(25)  # long enough to commit the term, short enough to click
    page.mouse.up()
    h.settle(page)
    h.expect_card(page, "GCD")
    h.wait_for_tree(page)
    assert h.selected_labels(page) == ["GCD (2022)"]
    assert h.address_param(page) == "69"
