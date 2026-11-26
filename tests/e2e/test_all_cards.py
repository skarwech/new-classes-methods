"""Every card, as the browser renders it, against what the CSV says."""

from __future__ import annotations

import pandas as pd
import pytest
from playwright.sync_api import Browser, Page

from explorer.abstracts import load_collection
from explorer.card import reference_text
from explorer.constants import CHECK_LABELS, CODE_LABELS, DATA_PATH
from explorer.links import paper_link_label, parse_code_alt, repo_name
from tests.test_text import EMOJI_OR_PICTOGRAPH

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def cards_page(browser: Browser, cards_url: str) -> Page:
    context = browser.new_context(viewport={"width": 1200, "height": 900})
    context.set_default_timeout(30_000)
    page = context.new_page()
    page.goto(cards_url)
    page.locator(".st-key-card-1").wait_for()
    page.locator(".st-key-card-N8").wait_for()
    return page


def expected_details(row: dict[str, str]) -> list[str]:
    names = ", ".join(
        n.strip() for n in row["authors_surnames"].split(";") if n.strip()
    )
    if names and row["authors_complete"] == "no":
        names += " et al."
    byline = f"{names} ({row['year']})" if names else ""
    return [line for line in (byline, row["title"], row["venue"]) if line]


def expected_links(row: dict[str, str]) -> list[str]:
    paper = (
        paper_link_label(row["paper_url"]) if row["paper_url"] else "no link recorded"
    )
    lines = [f"Paper: {paper}", f"Code: {CODE_LABELS[row['code_type']]}"]
    alternatives = parse_code_alt(row["code_alt"])
    if alternatives:
        labels = [
            f"{CODE_LABELS[a.kind]} ({repo_name(a.url)})".replace(" ()", "")
            for a in alternatives
        ]
        lines.append("Also: " + "; ".join(labels))
    lines.append(f"Reference check: {CHECK_LABELS[row['check']]}")
    return lines


def expected_abstract_paragraphs(row: dict[str, str]) -> list[str]:
    """The paragraphs after the links: the heading, and the text and source if any."""
    if not row["abstract"]:
        return ["Abstract: none recorded"]
    return ["Abstract", row["abstract"], f"Source: {row['abstract_source']}"]


def test_every_card_shows_exactly_what_the_data_says(cards_page: Page) -> None:
    problems = []
    for row in load_collection(DATA_PATH).to_dict(orient="records"):
        box = cards_page.locator(f".st-key-card-{row['id']}")
        heading = box.locator("h3").inner_text().strip()
        paragraphs = [text.strip() for text in box.locator("p").all_inner_texts()]
        shown_details = [line.strip() for line in paragraphs[0].split("\n")]
        shown_links = [line.strip() for line in paragraphs[1].split("\n")]
        reference = box.locator("pre").inner_text().strip()
        checks = {
            "heading": (heading, row["method"]),
            "details": (shown_details, expected_details(row)),
            "links": (shown_links, expected_links(row)),
            "abstract": (paragraphs[2:-1], expected_abstract_paragraphs(row)),
            "label": (paragraphs[-1], "Reference"),
            "reference": (reference, reference_text(row)),
        }
        problems += [
            f"{row['id']} {name}: {got!r} != {want!r}"
            for name, (got, want) in checks.items()
            if got != want
        ]
    assert not problems, "\n".join(problems[:10])


def test_every_link_in_every_card_is_a_safe_new_tab_link(
    cards_page: Page, methods: pd.DataFrame
) -> None:
    hrefs = cards_page.locator('[class*="st-key-card-"] a').evaluate_all(
        """links => links.map(a => [a.getAttribute('href'), a.target, a.rel])"""
    )
    assert len(hrefs) >= 250  # roughly 123 paper + 130 code + 57 alternative links
    for href, target, rel in hrefs:
        assert href.startswith(("https://", "http://")), href
        assert target == "_blank", href
        assert "noopener" in rel, href


def test_no_card_renders_emoji_math_or_images(cards_page: Page) -> None:
    assert cards_page.locator(".katex").count() == 0
    assert cards_page.locator("img").count() == 0
    text = cards_page.locator('[data-testid="stMain"]').inner_text()
    assert not EMOJI_OR_PICTOGRAPH.search(text)
