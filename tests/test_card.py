"""The detail card: byline, reference, links, labels and markdown escaping."""

from __future__ import annotations

import re

import pandas as pd
import pytest

from explorer.card import (
    author_names,
    byline,
    card_markdown,
    md_escape,
    reference_text,
)
from explorer.links import is_http_url
from tests.conftest import make_row

pytestmark = pytest.mark.unit


def row_of(methods: pd.DataFrame, row_id: str) -> dict[str, str]:
    return methods.loc[methods["id"] == row_id].iloc[0].to_dict()


# --- authors and byline ---------------------------------------------------------------


def test_author_names_join_surnames_with_commas(methods: pd.DataFrame) -> None:
    assert (
        author_names(row_of(methods, "1"))
        == "Scheirer, de Rezende Rocha, Sapkota, Boult"
    )


def test_et_al_is_added_only_when_the_list_is_incomplete(methods: pd.DataFrame) -> None:
    complete = row_of(methods, "5")
    assert complete["authors_complete"] == "yes"
    assert not author_names(complete).endswith("et al.")
    incomplete = row_of(methods, "79")  # LOOP
    assert incomplete["authors_complete"] == "no"
    assert author_names(incomplete).endswith(" Zhu et al.")


def test_single_surname_with_et_al(methods: pd.DataFrame) -> None:
    assert byline(row_of(methods, "148")) == "Arunthavanathan et al. (2020)"


def test_byline_shows_surnames_and_year(methods: pd.DataFrame) -> None:
    assert byline(row_of(methods, "4")) == "Bendale, Boult (2016)"


def test_no_recorded_authors_means_no_byline_and_no_dangling_et_al(
    methods: pd.DataFrame,
) -> None:
    alset = row_of(methods, "18")
    assert alset["authors_surnames"] == ""
    assert alset["authors_complete"] == "no"
    assert author_names(alset) == ""
    assert byline(alset) == ""


def test_byline_escapes_markdown() -> None:
    row = make_row(authors_surnames="O_Brien; A*B", year="2020")
    assert byline(row) == r"O\_Brien, A\*B (2020)"


# --- reference ------------------------------------------------------------------------


def test_reference_follows_the_authors_year_title_venue_pattern(
    methods: pd.DataFrame,
) -> None:
    assert reference_text(row_of(methods, "1")) == (
        "Scheirer, de Rezende Rocha, Sapkota, Boult (2013). "
        "Toward Open Set Recognition. IEEE TPAMI 35(7):1757–1772."
    )


def test_reference_with_et_al(methods: pd.DataFrame) -> None:
    row = row_of(methods, "148")
    assert reference_text(row).startswith("Arunthavanathan et al. (2020). ")


def test_reference_without_authors_leads_with_the_title(methods: pd.DataFrame) -> None:
    alset = row_of(methods, "18")
    text = reference_text(alset)
    assert text == f"{alset['title']} ({alset['year']}). {alset['venue']}."
    assert not text.startswith("(")


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {"title": "Is It Known?", "venue": "Venue X"},
            "Doe, Roe (2020). Is It Known? Venue X.",
        ),
        (
            {"title": "Ends With Dot.", "venue": "Venue X."},
            "Doe, Roe (2020). Ends With Dot. Venue X.",
        ),
        ({"title": "T", "venue": ""}, "Doe, Roe (2020). T."),
        ({"title": "", "venue": "V"}, "Doe, Roe (2020). V."),
        ({"title": "", "venue": ""}, "Doe, Roe (2020)."),
        (
            {"title": "A *starred* title", "venue": "V"},
            "Doe, Roe (2020). A *starred* title. V.",
        ),
    ],
)
def test_reference_punctuation(overrides: dict[str, str], expected: str) -> None:
    assert reference_text(make_row(**overrides)) == expected


# --- markdown escaping ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("plain text", "plain text"),
        (
            "Open Set Recognition: A Good Closed-Set Classifier",
            "Open Set Recognition: A Good Closed-Set Classifier",
        ),
        ("Ledoit & Wolf (2004)", r"Ledoit \& Wolf (2004)"),
        ("a*b*c", r"a\*b\*c"),
        ("snake_case_name", r"snake\_case\_name"),
        ("[link](http://x)", r"\[link\](http://x)"),
        ("`code`", r"\`code\`"),
        ("<b>bold</b>", r"\<b\>bold\</b\>"),
        ("cost $5 and $6", r"cost \$5 and \$6"),
        ("a|b", r"a\|b"),
        ("~~strike~~", r"\~\~strike\~\~"),
        ("back\\slash", r"back\\slash"),
        (":smile:", r"\:smile:"),
        (":red[text]", r"\:red\[text\]"),
        ("# heading", r"\# heading"),
        ("> quote", r"\> quote"),
        ("- item", r"\- item"),
        ("+ item", r"\+ item"),
        ("1. item", r"1\. item"),
        ("2) item", r"2\) item"),
        ("", ""),
        ("Foo #", r"Foo \#"),  # a trailing # would close a heading
        ("C#", r"C\#"),
        ("## H2 ##", r"\#\# H2 \#\#"),
        ("===", r"\==="),  # would underline the line above as a heading
        ("---", r"\---"),
        ("--", r"\--"),
        ("-", r"\-"),
    ],
)
def test_md_escape(raw: str, escaped: str) -> None:
    assert md_escape(raw) == escaped


def test_md_escape_leaves_inner_hyphens_and_dots_alone() -> None:
    assert md_escape("Time-Series Open-set v2.0") == "Time-Series Open-set v2.0"


# --- the card -------------------------------------------------------------------------


def test_card_for_a_method_with_an_official_repository_and_a_library_alternative(
    methods: pd.DataFrame,
) -> None:
    card = card_markdown(row_of(methods, "4"))
    assert card.startswith("### OpenMax")
    assert "Bendale, Boult (2016)" in card
    assert "*Towards Open Set Deep Networks*" in card
    assert "CVPR 2016" in card
    assert "**Paper:** [arXiv](https://arxiv.org/abs/1511.06233)" in card
    assert "**Code:** [Official code](https://github.com/abhijitbendale/OSDN)" in card
    assert (
        "Also: [Library implementation (OpenOOD)]"
        "(https://github.com/Jingkang50/OpenOOD/blob/HEAD/openood/postprocessors/openmax_postprocessor.py)"
    ) in card
    assert "**Reference check:** Checked against the source" in card
    assert card.rstrip().endswith("**Reference**")


def test_card_without_public_code_says_so_in_words_and_has_no_code_link(
    methods: pd.DataFrame,
) -> None:
    row = methods.loc[methods["code_type"] == "none"].iloc[0].to_dict()
    card = card_markdown(row)
    assert "**Code:** No public code found" in card
    code_line = next(line for line in card.splitlines() if line.startswith("**Code:**"))
    assert "](" not in code_line
    assert "Also:" not in card


def test_card_without_a_paper_link_has_no_dead_link(methods: pd.DataFrame) -> None:
    row = methods.loc[methods["paper_url"] == ""].iloc[0].to_dict()
    card = card_markdown(row)
    paper_line = next(
        line for line in card.splitlines() if line.startswith("**Paper:**")
    )
    assert (
        paper_line.rstrip() == "**Paper:** no link recorded"
    )  # (a hard break may follow)


def test_card_for_a_method_without_authors_has_no_author_line(
    methods: pd.DataFrame,
) -> None:
    card = card_markdown(row_of(methods, "18"))
    blocks = card.split("\n\n")
    assert blocks[0] == "### ALSET"
    assert blocks[1].startswith("*Time-Series Open-set Recognition")
    assert "et al." not in card
    assert "(2025)" in blocks[1]  # the venue line still carries the year


def test_a_row_with_no_authors_title_or_venue_still_gives_a_card() -> None:
    card = card_markdown(make_row(authors_surnames="", title="", venue=""))
    blocks = card.split("\n\n")
    assert blocks[0] == "### Method"
    assert blocks[1].startswith(
        "**Paper:**"
    )  # straight on to the links: no empty detail block
    assert blocks[-1] == "**Reference**"


@pytest.mark.parametrize(
    ("kind", "label"),
    [
        ("official", "Official code"),
        ("third-party", "Third-party implementation"),
        ("library", "Library implementation"),
    ],
)
def test_primary_code_link_is_labeled_in_words(
    methods: pd.DataFrame, kind: str, label: str
) -> None:
    row = methods.loc[methods["code_type"] == kind].iloc[0].to_dict()
    card = card_markdown(row)
    assert f"**Code:** [{label}](" in card


@pytest.mark.parametrize(
    ("value", "words"),
    [
        ("V", "Checked against the source"),
        ("C", "Not re-checked"),
        ("C?", "Incomplete or flagged: check before citing"),
    ],
)
def test_reference_check_is_said_in_plain_words(value: str, words: str) -> None:
    assert f"**Reference check:** {words}" in card_markdown(make_row(check=value))


def test_several_alternatives_are_listed_on_one_also_line(
    methods: pd.DataFrame,
) -> None:
    row = row_of(methods, "93")  # LwF: PyCIL and Avalanche
    card = card_markdown(row)
    also = next(line for line in card.splitlines() if line.startswith("Also:"))
    assert also.count("](") == 2
    assert "(PyCIL)" in also
    assert "(avalanche)" in also


def test_untrusted_text_is_escaped_inside_the_card() -> None:
    row = make_row(
        method="A_B*C", title="Use [x] and $y$", venue="V|W", authors_surnames="Q_R"
    )
    card = card_markdown(row)
    assert card.startswith(r"### A\_B\*C")
    assert r"*Use \[x\] and \$y\$*" in card
    assert r"V\|W" in card
    assert r"Q\_R (2020)" in card


def test_link_destinations_in_a_card_are_encoded() -> None:
    row = make_row(
        paper_url="https://doi.org/10.1002/(SICI)1097-0258(19980815/30)17:15/16<1661::AID-SIM968>3.0.CO;2-2",
        code_type="official",
        code_url="https://github.com/a/b_(c)",
    )
    card = card_markdown(row)
    assert "(SICI)" not in card
    assert "<1661" not in card
    assert "%28SICI%29" in card
    assert "%3C1661" in card
    assert "https://github.com/a/b_%28c%29" in card


def test_every_card_in_the_collection_builds_with_safe_links(
    methods: pd.DataFrame,
) -> None:
    destination = re.compile(r"\]\(([^)]*)\)")
    for row in methods.to_dict(orient="records"):
        card = card_markdown(row)
        assert card.startswith("### "), row["id"]
        for url in destination.findall(card):
            assert is_http_url(url), (row["id"], url)
            assert not set(url) & set('()<> []"\\'), (row["id"], url)
        assert md_escape(row["title"]) in card, row["id"]
        assert md_escape(row["venue"]) in card, row["id"]
        assert reference_text(row).endswith((".", "?", "!")), row["id"]
