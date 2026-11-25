"""Page layout on a desktop and on a phone, the how-to-read expander, the CSV download."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from explorer import text
from explorer.constants import PUBLIC_COLUMNS, TREE_HEIGHT
from tests.e2e import helpers as h

pytestmark = pytest.mark.e2e

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


def shot(page: Page, name: str) -> None:
    ARTIFACTS.mkdir(exist_ok=True)
    page.screenshot(path=str(ARTIFACTS / f"{name}.png"), full_page=True)


def test_desktop_layout_has_the_tree_left_of_the_card_and_the_sidebar_open(
    open_at,
) -> None:
    page = open_at("?m=4")
    h.expect_card(page, "OpenMax")
    h.settle(page)
    tree_box = page.locator(h.TREE_IFRAME).bounding_box()
    heading_box = page.locator('[data-testid="stMain"] h3').bounding_box()
    assert tree_box["x"] < heading_box["x"]  # side by side
    assert abs(tree_box["height"] - TREE_HEIGHT) <= 2
    columns = page.locator('[data-testid="stColumn"]').all()
    left, right = (column.bounding_box()["width"] for column in columns[:2])
    assert 1.15 < left / right < 1.35  # 5 : 4
    expect(page.locator('[data-testid="stSidebar"]')).to_contain_text(
        "Search and filters"
    )
    expect(page.get_by_label("Search", exact=True)).to_be_visible()
    shot(page, "desktop_openmax")


def test_the_title_and_the_two_line_description_are_there(page: Page) -> None:
    expect(page.get_by_role("heading", level=1)).to_have_text(text.TITLE)
    description = page.get_by_text("170 methods for recognizing, discovering").first
    expect(description).to_be_visible()
    expect(
        page.get_by_text("Select a method to see its reference").first
    ).to_be_visible()


def test_the_how_to_read_expander_opens_and_does_not_rerun_the_script(
    page: Page,
) -> None:
    before = h.settle(page)
    page.get_by_text("How to read", exact=True).click()
    expect(
        page.get_by_text("Third-party implementation: a repository").first
    ).to_be_visible()
    assert h.settle(page) == before


def test_the_download_gives_the_filtered_rows_as_csv(page: Page) -> None:
    h.search(page, "halasz")
    h.expect_counter(page, "2 of 170 methods")
    before = h.settle(page)
    with page.expect_download() as download_info:
        page.get_by_role("button", name="Download filtered rows (CSV)").click()
    download = download_info.value
    assert download.suggested_filename == "methods_filtered.csv"
    text = Path(download.path()).read_bytes().decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert [row["id"] for row in rows] == ["N3", "N4"]
    assert list(rows[0]) == list(PUBLIC_COLUMNS)
    assert rows[0]["method"].startswith("Halász")  # accents survive
    assert h.settle(page) == before  # the click does not rerun the script


def test_no_javascript_errors_during_a_typical_visit(open_at) -> None:
    page = open_at("")
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    h.wait_for_tree(page)
    h.click_row(page, "Unknown Rejection (63)")
    h.search(page, "halasz")
    h.expect_counter(page, "2 of 170 methods")
    h.search(page, "")
    page.wait_for_timeout(800)
    assert errors == []


# --- a phone (390 px wide) -----------------------------------------------------------


def test_on_a_phone_the_columns_stack_and_the_card_sits_under_the_tree(
    phone: Page,
) -> None:
    h.wait_for_tree(phone)
    width = phone.evaluate("window.innerWidth")
    assert phone.evaluate("document.documentElement.scrollWidth") <= width + 1
    h.click_row(phone, "Unknown Rejection (63)")
    h.click_row(phone, "1.1 Discriminative Open Set Recognition (19)")
    h.click_row(phone, "Extreme-value calibrated (2)")
    h.click_row(phone, "OpenMax (2016)")
    h.expect_card(phone, "OpenMax")
    tree_box = phone.locator(h.TREE_IFRAME).bounding_box()
    heading_box = phone.locator('[data-testid="stMain"] h3').bounding_box()
    assert (
        heading_box["y"] >= tree_box["y"] + tree_box["height"] - 2
    )  # below, not beside
    assert tree_box["width"] <= width
    assert phone.evaluate("document.documentElement.scrollWidth") <= width + 1
    shot(phone, "phone_openmax")


def test_on_a_phone_the_sidebar_starts_closed_and_can_be_opened(phone: Page) -> None:
    h.wait_for_tree(phone)
    sidebar = phone.locator('[data-testid="stSidebar"]')
    assert sidebar.get_attribute("aria-expanded") in ("false", None)
    phone.locator('[data-testid="stExpandSidebarButton"]').click()
    expect(phone.get_by_label("Search", exact=True)).to_be_visible()
    shot(phone, "phone_sidebar")


def test_on_a_phone_a_deep_link_works(open_at) -> None:
    page = open_at("?m=N4", viewport={"width": 390, "height": 844})
    h.wait_for_tree(page)
    assert h.selected_labels(page) == ["Halász et al. (fake features) (2023)"]
    h.expect_card(page, "Halász et al. (fake features)")
