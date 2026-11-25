"""Small helpers for driving the page: the tree (an iframe), the sidebar and the card."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import FrameLocator, Locator, Page, expect

TREE_IFRAME = 'iframe[title*="arborist"]'
WAIT_MS = 15_000


@dataclass(frozen=True)
class Row:
    """One visible row of the tree."""

    label: str
    level: int  # 1 for a family
    is_folder: bool
    expanded: bool | None  # None for a method (it cannot be opened)
    selected: bool


# --- the tree --------------------------------------------------------------------


def tree(page: Page) -> FrameLocator:
    return page.frame_locator(TREE_IFRAME)


def tree_items(page: Page) -> Locator:
    return tree(page).locator('[role="treeitem"]')


def wait_for_tree(page: Page) -> None:
    """Wait until one tree is drawn. While a new tree replaces an old one, Streamlit
    keeps both iframes for a moment, so wait for the old one to go."""
    expect(page.locator(TREE_IFRAME)).to_have_count(1, timeout=WAIT_MS)
    expect(tree_items(page).first).to_be_visible(timeout=WAIT_MS)


def rows(page: Page) -> list[Row]:
    """The rows currently drawn (the tree only draws what fits in its window)."""
    wait_for_tree(page)
    found = tree_items(page).evaluate_all("""els => els.map(e => ({
            label: e.innerText.trim(),
            level: Number(e.getAttribute('aria-level')),
            folder: e.firstElementChild.classList.contains('isInternal'),
            open: e.getAttribute('aria-expanded') === 'true',
            selected: e.getAttribute('aria-selected') === 'true',
        }))""")
    return [
        Row(
            label=item["label"],
            level=item["level"],
            is_folder=item["folder"],
            expanded=item["open"] if item["folder"] else None,
            selected=item["selected"],
        )
        for item in found
    ]


def labels(page: Page) -> list[str]:
    return [row.label for row in rows(page)]


def row(page: Page, label: str) -> Locator:
    exact = re.compile(rf"^{re.escape(label)}$")
    return tree_items(page).filter(has_text=exact)


def click_row(page: Page, label: str) -> None:
    wait_for_tree(page)
    row(page, label).click(timeout=WAIT_MS)


def selected_labels(page: Page) -> list[str]:
    return [item.label for item in rows(page) if item.selected]


def open_labels(page: Page) -> list[str]:
    return [item.label for item in rows(page) if item.expanded]


# --- the sidebar -------------------------------------------------------------------


def search_box(page: Page) -> Locator:
    return page.get_by_label("Search", exact=True)


def search(page: Page, text: str) -> None:
    box = search_box(page)
    box.fill(text)
    box.press("Enter")


def counter(page: Page) -> str:
    return page.locator('[data-testid="stSidebar"] strong').first.inner_text()


def expect_counter(page: Page, text: str) -> None:
    expect(page.locator('[data-testid="stSidebar"] strong').first).to_have_text(
        text, timeout=WAIT_MS
    )


# --- the card and the address ------------------------------------------------------


def card_heading(page: Page) -> str | None:
    headings = page.locator('[data-testid="stMain"] h3')
    return headings.first.inner_text().strip() if headings.count() else None


def expect_card(page: Page, heading: str | None) -> None:
    """The card shows ``heading``, or the how-to-read text when ``heading`` is None."""
    main = page.locator('[data-testid="stMain"]')
    columns = page.locator('[data-testid="stHorizontalBlock"]')  # tree | card
    if heading is None:
        expect(main.locator("h3")).to_have_count(0, timeout=WAIT_MS)
        expect(
            columns.get_by_text("Official code: the authors' own repository")
        ).to_be_visible(timeout=WAIT_MS)
    else:
        expect(main.locator("h3").first).to_have_text(heading, timeout=WAIT_MS)


def address_param(page: Page, name: str = "m") -> str | None:
    values = parse_qs(urlsplit(page.url).query).get(name)
    return values[0] if values else None


# --- reruns ----------------------------------------------------------------------


def script_runs(page: Page) -> int | None:
    """The run counter of the instrumented app, or None when it is not shown."""
    caption = page.get_by_text(re.compile(r"^script runs: \d+$"))
    if not caption.count():
        return None
    return int(caption.first.inner_text().rsplit(" ", 1)[1])


def counter_expected() -> bool:
    """True when the app was started by the tests, so the run counter must be there."""
    return not os.environ.get("E2E_BASE_URL")


def settle(page: Page, quiet_ms: int = 1_500, give_up_ms: int = 12_000) -> int | None:
    """Wait until the run count stops changing; fail if it keeps going (a rerun loop)."""
    waited = 0
    if counter_expected():  # the page may still be drawing: wait for the counter
        counter_text = page.get_by_text(re.compile(r"^script runs: \d+$")).first
        expect(counter_text).to_be_visible(timeout=WAIT_MS)
    last = script_runs(page)
    stable_for = 0
    while stable_for < quiet_ms:
        page.wait_for_timeout(250)
        waited += 250
        now = script_runs(page)
        stable_for = stable_for + 250 if now == last else 0
        last = now
        if waited > give_up_ms:
            raise AssertionError(
                f"page is still rerunning after {waited} ms (runs: {last})"
            )
    return last


# --- sidebar choices -----------------------------------------------------------------


def choose(page: Page, label: str, option: str) -> None:
    """Pick ``option`` in the multiselect called ``label``."""
    box = page.locator('[data-testid="stMultiSelect"]').filter(has_text=label)
    box.locator("input").click()
    page.get_by_role("option", name=option, exact=True).click()
    page.keyboard.press("Escape")


# --- slowing the browser down ------------------------------------------------------


def throttle_cpu(page: Page, rate: float) -> None:
    """Make the browser ``rate`` times slower, to widen the window of a race."""
    page.context.new_cdp_session(page).send(
        "Emulation.setCPUThrottlingRate", {"rate": rate}
    )
