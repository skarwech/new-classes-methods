"""The detail card as a visitor sees it: links, labels, the reference block."""

from __future__ import annotations

import pandas as pd
import pytest
from playwright.sync_api import Page, expect

from explorer.card import reference_text
from tests.e2e import helpers as h

pytestmark = pytest.mark.e2e


def card_area(page: Page):
    """The right-hand column (the card), not the collapsed expander at the top."""
    return page.locator('[data-testid="stHorizontalBlock"]')


def row_of(methods: pd.DataFrame, row_id: str) -> dict[str, str]:
    return methods.loc[methods["id"] == row_id].iloc[0].to_dict()


def test_links_open_in_a_new_tab_and_say_what_they_are(open_at) -> None:
    page = open_at("?m=4")
    h.expect_card(page, "OpenMax")
    area = card_area(page)

    paper = area.get_by_role("link", name="arXiv", exact=True).first  # the paper link
    expect(paper).to_have_attribute("href", "https://arxiv.org/abs/1511.06233")
    expect(paper).to_have_attribute("target", "_blank")
    expect(paper).to_have_attribute("rel", "noopener noreferrer")

    code = area.get_by_role("link", name="Official code", exact=True)
    expect(code).to_have_attribute("href", "https://github.com/abhijitbendale/OSDN")
    expect(code).to_have_attribute("target", "_blank")

    also = area.get_by_role("link", name="Library implementation (OpenOOD)")
    expect(also).to_have_attribute("target", "_blank")
    assert "openmax_postprocessor.py" in (also.get_attribute("href") or "")
    expect(area.get_by_text("Checked against the source")).to_be_visible()


def test_the_reference_is_plain_text_in_a_code_block_for_copying(
    open_at, methods: pd.DataFrame
) -> None:
    page = open_at("?m=1")
    h.expect_card(page, "1-vs-Set")
    block = card_area(page).locator("pre")
    expect(block).to_have_text(reference_text(row_of(methods, "1")))
    assert reference_text(row_of(methods, "1")).startswith("Scheirer, de Rezende Rocha")


def test_a_method_without_a_paper_link_shows_no_dead_link(open_at) -> None:
    page = open_at("?m=3")  # PI-SVM has a code link but no paper link
    h.expect_card(page, "PI-SVM")
    area = card_area(page)
    expect(area.get_by_text("no link recorded")).to_be_visible()
    hrefs = [link.get_attribute("href") for link in area.get_by_role("link").all()]
    assert hrefs == ["https://github.com/Vastlab/libsvm-openset"]  # only the code link


def test_a_method_without_public_code_says_so_in_words(
    open_at, methods: pd.DataFrame
) -> None:
    row = methods.loc[methods["code_type"] == "none"].iloc[0]
    page = open_at(f"?m={row['id']}")
    h.expect_card(page, row["method"])
    area = card_area(page)
    expect(area.get_by_text("No public code found")).to_be_visible()
    assert not [
        link
        for link in area.get_by_role("link").all()
        if "github.com" in (link.get_attribute("href") or "")
    ]


def test_a_method_without_recorded_authors_has_no_author_line(open_at) -> None:
    page = open_at("?m=18")
    h.expect_card(page, "ALSET")
    area = card_area(page)
    first_paragraph = area.locator("p").first.inner_text()
    assert first_paragraph.startswith("Time-Series Open-set Recognition")
    assert "et al." not in area.inner_text().split("Reference check")[0]


def test_an_incomplete_author_list_ends_in_et_al(open_at) -> None:
    page = open_at("?m=79")  # LOOP: ten surnames recorded, list incomplete
    h.expect_card(page, "LOOP")
    first_paragraph = card_area(page).locator("p").first.inner_text()
    assert first_paragraph.split("\n")[0].startswith("An, Shi, Tian")
    assert " et al. (" in first_paragraph.split("\n")[0]


def test_text_with_markdown_characters_is_shown_literally(open_at) -> None:
    page = open_at("?m=155")  # "Gibbs & Candès (2021)"
    h.expect_card(page, "Gibbs & Candès (2021)")


def test_clicking_in_the_tree_shows_the_same_card_as_the_deep_link(page: Page) -> None:
    h.wait_for_tree(page)
    h.click_row(page, "Unknown Rejection (63)")
    h.click_row(page, "1.1 Discriminative Open Set Recognition (19)")
    h.click_row(page, "Extreme-value calibrated (2)")
    h.click_row(page, "OpenMax (2016)")
    h.expect_card(page, "OpenMax")
    area = card_area(page)
    expect(area.get_by_role("link", name="Official code", exact=True)).to_be_visible()
    expect(area.locator("pre")).to_contain_text("Bendale, Boult (2016)")


def test_the_abstract_is_shown_with_its_source_between_the_details_and_the_reference(
    open_at,
) -> None:
    page = open_at("?m=4")
    h.expect_card(page, "OpenMax")
    area = card_area(page)
    expect(
        area.get_by_text("Deep networks have produced significant gains")
    ).to_be_visible()
    source = area.get_by_role("link", name="arXiv", exact=True).nth(
        1
    )  # paper link comes first
    expect(source).to_have_attribute("href", "https://arxiv.org/abs/1511.06233")
    expect(source).to_have_attribute("target", "_blank")
    order = area.inner_text()
    assert (
        order.index("Reference check")
        < order.index("Abstract")
        < order.index("Reference\n")
    )


def test_a_method_without_an_abstract_says_so_and_still_has_its_reference(
    open_at,
) -> None:
    page = open_at("?m=112")  # MINAS
    h.expect_card(page, "MINAS")
    area = card_area(page)
    expect(area.get_by_text("none recorded")).to_be_visible()
    expect(area.locator("pre")).to_contain_text("Faria, de Carvalho, Gama")


def test_the_how_to_read_text_explains_abstracts(page: Page) -> None:
    expect(h.tree(page).locator('[role="treeitem"]').first).to_be_visible()
    page.get_by_text("How to read", exact=True).click()
    expect(
        page.get_by_text("Abstracts were retrieved automatically").first
    ).to_be_visible()
