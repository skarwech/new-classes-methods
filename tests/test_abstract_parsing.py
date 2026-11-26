"""Abstract fetcher, pure parts: titles, identifiers, cleaning and the source parsers."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from explorer.constants import ABSTRACT_MATCHES, ABSTRACT_SOURCES, MAX_ABSTRACT_CHARS
from explorer.data import has_control_character
from tests.abstract_fixtures import (
    AT,
    ATOM,
    CVF_HTML,
    LONG,
    PMLR_HTML,
    found,
    openalex_work,
    row,
)
from tools import abstract_parsing
from tools.abstract_parsing import (
    MAX_PAGE_CHARS,
    MAX_RAW_CHARS,
    MAX_URL_CHARS,
    accept,
    arxiv_id_of,
    clean_abstract,
    deinvert,
    doi_of,
    has_hidden_character,
    normalize_title,
    openalex_item,
    parse_arxiv_atom,
    parse_crossref_work,
    parse_cvf,
    parse_openalex_work,
    parse_pmlr,
    strip_invisible,
    title_similarity,
    url_problem,
)

pytestmark = pytest.mark.unit


# --- titles ---------------------------------------------------------------------------


def test_normalize_title_ignores_case_accents_and_punctuation() -> None:
    assert normalize_title("Halász: Open-Set  Learning!") == "halasz open set learning"


def test_similar_titles_score_high_and_different_titles_low() -> None:
    assert (
        title_similarity(
            "Towards Open Set Deep Networks", "towards open-set deep networks"
        )
        == 1.0
    )
    assert (
        title_similarity("The Extreme Value Machine", "The Extreme Value Machine.")
        > 0.95
    )
    assert (
        title_similarity("Toward Open Set Recognition", "Deep Residual Learning") < 0.5
    )


def test_titles_with_no_letters_or_digits_never_match() -> None:
    assert title_similarity("日本語", "中文") == 0.0
    assert title_similarity("", "") == 0.0
    assert not accept(row(title="日本語"), found("中文"))


def test_an_identifier_match_needs_a_similar_title() -> None:
    r = row()
    assert accept(r, found("Towards Open Set Deep Networks"))
    assert accept(r, found("Towards open-set deep networks: an extended version"))
    assert not accept(r, found("A completely different paper about graphs"))


def test_a_short_title_is_not_a_match_just_because_it_is_inside_a_longer_one() -> None:
    r = row(title="Generalized Category Discovery")
    assert not accept(
        r, found("Generalized Category Discovery for Open World Learning")
    )
    assert not accept(row(title="Foo Bar"), found("Foo Bar Baz Qux Quux Corge"))


def test_a_title_search_match_is_stricter_and_checks_the_year() -> None:
    r = row(year="2016")
    assert accept(r, found("Towards Open Set Deep Networks", year=2016, how="title"))
    assert accept(r, found("Towards Open Set Deep Networks", year=2015, how="title"))
    assert not accept(
        r, found("Towards Open Set Deep Networks", year=2009, how="title")
    )
    assert not accept(
        r,
        found("Towards Open Set Deep Network Training Tricks", year=2016, how="title"),
    )
    assert not accept(
        r, found("Towards Open Set Deep Networks", year=None, how="title")
    )


def test_a_year_that_is_not_ascii_digits_cannot_crash_the_title_check() -> None:
    assert not accept(
        row(year="²"), found("Towards Open Set Deep Networks", year=2016, how="title")
    )


def _surnames(record: dict[str, str]) -> tuple[str, ...]:
    """The authors of a method as a source would list them (surnames are enough)."""
    return tuple(n.strip() for n in record["authors_surnames"].split(";") if n.strip())


def test_no_two_different_methods_of_the_collection_match_each_other(
    methods: pd.DataFrame,
) -> None:
    """A wrong identifier that points at a sibling paper must not be accepted."""
    rows = methods.to_dict(orient="records")
    clashes = [
        (a["id"], b["id"])
        for a in rows
        for b in rows
        if a["id"] != b["id"] and accept(a, found(b["title"], authors=_surnames(b)))
    ]
    assert clashes == []


# --- identifiers ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"arxiv": "1511.06233"}, "1511.06233"),
        ({"arxiv": "arXiv:1511.06233v2"}, "1511.06233"),
        ({"arxiv": "arxiv:1511.06233"}, "1511.06233"),
        ({"paper_url": "https://arxiv.org/abs/1511.06233v3"}, "1511.06233"),
        ({"paper_url": "https://arxiv.org/abs/1511.06233/"}, "1511.06233"),
        (
            {"arxiv": "\u0661\u0662\u0663\u0664.\u0665\u0666\u0667\u0668"},
            "",
        ),  # Arabic digits
        ({"arxiv": "hep-th/\u0669\u0669\u0660\u0661\u0660\u0660\u0661"}, ""),
        ({"paper_url": "https://www.arxiv.org/abs/1511.06233"}, "1511.06233"),
        ({"paper_url": "https://arxiv.org/pdf/1511.06233.pdf"}, "1511.06233"),
        ({"paper_url": "https://arxiv.org/abs/hep-th/9901001"}, "hep-th/9901001"),
        (
            {"arxiv": "1511.06233", "paper_url": "https://arxiv.org/abs/9999.99999"},
            "1511.06233",
        ),
        ({"paper_url": "https://doi.org/10.1109/X"}, ""),
        ({}, ""),
    ],
)
def test_arxiv_id_of(fields: dict[str, str], expected: str) -> None:
    assert arxiv_id_of(row(**fields)) == expected


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"doi": "10.1109/TPAMI.2012.256"}, "10.1109/TPAMI.2012.256"),
        ({"doi": "https://doi.org/10.1109/TPAMI.2012.256"}, "10.1109/TPAMI.2012.256"),
        (
            {"paper_url": "https://doi.org/10.1007/978-3-031-05936-0_28"},
            "10.1007/978-3-031-05936-0_28",
        ),
        ({"paper_url": "https://dx.doi.org/10.1109/X"}, "10.1109/X"),
        ({"paper_url": "https://doi.org/10.1002/%28SICI%291097"}, "10.1002/(SICI)1097"),
        ({"doi": "10.1/a", "paper_url": "https://doi.org/10.9/b"}, "10.1/a"),
        ({"paper_url": "https://arxiv.org/abs/1511.06233"}, ""),
        ({"doi": "10.1000/../../people"}, ""),  # would climb out of the DOI path
        ({"doi": "10.1000/a/./b"}, ""),
        ({"paper_url": "https://doi.org/10.1000/%2e%2e/x"}, ""),
        ({"doi": "10.\u0661\u0660\u0660\u0660/x"}, ""),
        ({"doi": "10.1000/a b"}, ""),
        ({"doi": "11.1000/x"}, ""),
        ({}, ""),
    ],
)
def test_doi_of(fields: dict[str, str], expected: str) -> None:
    assert doi_of(row(**fields)) == expected


# --- cleaning -------------------------------------------------------------------------


def test_deinvert_puts_words_back_in_order() -> None:
    assert (
        deinvert({"world": [1], "Hello": [0], "again": [2, 3]})
        == "Hello world again again"
    )
    assert deinvert(None) == ""
    assert deinvert({}) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"<jats:p>{LONG}</jats:p>", LONG),
        (f"Abstract. {LONG}", LONG),
        (f"ABSTRACT: {LONG}", LONG),
        (
            f"<jats:title>Abstract</jats:title><jats:p>{LONG} &amp; more</jats:p>",
            LONG + " & more",
        ),
        (f"  {LONG}\n\n   {LONG}  ", LONG + " " + LONG),
        (f"Abstract concepts are hard. {LONG}", f"Abstract concepts are hard. {LONG}"),
        (
            f"Abstract-level features help. {LONG}",
            f"Abstract-level features help. {LONG}",
        ),
        (f"Abstract - {LONG}", LONG),
        ("Abstract", ""),
        ("n/a", ""),
        ("", ""),
    ],
)
def test_clean_abstract(raw: str, expected: str) -> None:
    assert clean_abstract(raw) == expected


def test_inline_markup_does_not_leave_stray_spaces_but_block_markup_separates() -> None:
    raw = f"We use <jats:italic>k</jats:italic>-nearest and H<sub>2</sub>O.<br/>{LONG}<p>Next paragraph.</p>"
    cleaned = clean_abstract(raw)
    assert "k-nearest and H2O." in cleaned
    assert cleaned.endswith("Next paragraph.")
    assert "H2O. Traditional classifiers" in cleaned  # a line break separates words
    assert "categories. Next paragraph." in cleaned  # and so does a paragraph
    assert ".<br" not in cleaned
    assert "  " not in cleaned


def test_clean_abstract_drops_text_that_is_too_short_to_be_one() -> None:
    assert clean_abstract("Too short to be an abstract.") == ""


def test_text_that_is_not_markup_keeps_its_comparison_signs() -> None:
    text = "for $p < 0.05$ and $q > 0.1$ the error is small. " * 3
    assert clean_abstract(text, markup=False) == text.strip()
    assert "<" not in clean_abstract(text)  # as markup, "< ... >" would be a tag


@pytest.mark.parametrize(
    "invisible",
    ["​", "﻿", "‎", "‮", "⁠", "\x7f", "\x00", "؜", "\U000e0041"],
)
def test_invisible_characters_are_removed_and_never_reach_the_file(
    invisible: str,
) -> None:
    raw = f"{LONG[:60]}{invisible}{LONG[60:]} " * 2
    cleaned = clean_abstract(raw, markup=False)
    assert invisible not in cleaned
    assert not has_control_character(cleaned)
    assert cleaned.startswith(LONG[:60])


def test_strip_invisible_keeps_ordinary_text_and_whitespace() -> None:
    assert strip_invisible("a\tb\nc d e") == "a\tb\nc d e"
    assert strip_invisible("a​b") == "ab"


# --- the sources ----------------------------------------------------------------------


def test_parse_arxiv_atom_gives_unversioned_ids_collapsed_text_and_the_year() -> None:
    found_ = parse_arxiv_atom(ATOM)
    assert sorted(found_) == ["1506.06112", "1511.06233"]  # the error entry is skipped
    evm = found_["1506.06112"]
    assert evm.title == "The Extreme Value Machine"
    assert evm.text.startswith("Traditional classifiers")
    assert "\n" not in evm.text
    assert "  " not in evm.text
    assert "$\\ell_2$ math" in evm.text
    assert (evm.source, evm.year) == ("arXiv", 2015)
    assert evm.url == "https://arxiv.org/abs/1506.06112"


def test_arxiv_text_with_less_than_and_greater_than_signs_is_kept_whole() -> None:
    body = (
        "We test, for $p &lt; 0.05$ and $q &gt; 0.1$, whether the error stays small in all settings. "
        * 2
    )
    feed = f"<feed><entry><id>http://arxiv.org/abs/1234.56789v1</id><title>T</title><summary>{body}</summary></entry></feed>"
    text = parse_arxiv_atom(feed)["1234.56789"].text
    assert "$p < 0.05$ and $q > 0.1$" in text


@pytest.mark.parametrize("bad", ["", "not xml", "<feed/>"])
def test_parse_arxiv_atom_survives_garbage(bad: str) -> None:
    assert parse_arxiv_atom(bad) == {}


def test_an_entity_defined_in_a_dtd_is_not_expanded() -> None:
    """There is no XML parser, so a document type definition cannot expand anything."""
    body = (
        "A text that mentions &a; once and is long enough to be kept as an abstract. "
        * 3
    )
    feed = (
        '<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY a "aaaa">]><feed><entry>'
        f"<id>http://arxiv.org/abs/1234.56789v1</id><title>T</title><summary>{body}</summary>"
        "</entry></feed>"
    )
    assert "mentions &a; once" in parse_arxiv_atom(feed)["1234.56789"].text


def test_an_arxiv_entry_without_a_usable_abstract_is_skipped() -> None:
    feed = (
        "<feed><entry><id>http://arxiv.org/abs/1511.06233v1</id>"
        "<title>T</title><summary>n/a</summary></entry></feed>"
    )
    assert parse_arxiv_atom(feed) == {}


def test_parse_openalex_work() -> None:
    parsed = parse_openalex_work(openalex_work(), matched_by="doi")
    assert parsed is not None
    assert parsed.text == LONG
    assert (parsed.source, parsed.matched_by, parsed.year) == ("OpenAlex", "doi", 2012)
    assert parsed.url == "https://openalex.org/W2119880843"


def test_an_openalex_work_without_an_id_falls_back_to_its_doi_and_never_has_an_empty_link() -> (
    None
):
    parsed = parse_openalex_work(openalex_work(work_id=""), matched_by="doi")
    assert parsed is not None
    assert parsed.url == "https://doi.org/10.1109/tpami.2012.256"
    payload = json.loads(openalex_work(work_id=""))
    del payload["doi"]
    assert parse_openalex_work(json.dumps(payload), matched_by="doi") is None


def test_openalex_item_takes_an_already_parsed_work() -> None:
    parsed = openalex_item(json.loads(openalex_work()), matched_by="title")
    assert parsed is not None
    assert parsed.matched_by == "title"
    assert openalex_item({"title": "x"}, matched_by="title") is None


def test_parse_openalex_work_without_an_abstract_gives_nothing() -> None:
    payload = json.loads(openalex_work())
    payload["abstract_inverted_index"] = None
    assert parse_openalex_work(json.dumps(payload), matched_by="doi") is None
    assert parse_openalex_work("not json", matched_by="doi") is None


def test_a_crossref_record_without_an_abstract_gives_nothing() -> None:
    record = json.dumps({"message": {"title": ["Toward Open Set Recognition"]}})
    assert parse_crossref_work(record, "10.1/x") is None
    assert parse_crossref_work("not json", "10.1/x") is None


def test_parse_crossref_work() -> None:
    record = json.dumps(
        {"message": {"title": ["T"], "abstract": f"<jats:p>{LONG}</jats:p>"}}
    )
    parsed = parse_crossref_work(record, "10.1/x")
    assert parsed is not None
    assert (parsed.source, parsed.url, parsed.text) == (
        "Crossref",
        "https://doi.org/10.1/x",
        LONG,
    )


def test_parse_cvf_and_pmlr_pages() -> None:
    url = "https://openaccess.thecvf.com/content/CVPR2021/html/x.html"
    cvf = parse_cvf(CVF_HTML, url)
    assert cvf is not None
    assert cvf.title == "Learning Placeholders for Open-Set Recognition"
    assert cvf.text == LONG
    assert (cvf.source, cvf.url, cvf.matched_by) == ("CVF", url, "paper url")
    pmlr = parse_pmlr(PMLR_HTML, "https://proceedings.mlr.press/v199/x.html")
    assert pmlr is not None
    assert pmlr.title.startswith("Streaming Inference")
    assert pmlr.source == "PMLR"
    assert parse_cvf("<html></html>", url) is None
    assert parse_pmlr("<html></html>", url) is None


def test_openalex_plain_text_keeps_comparison_signs_but_copied_markup_is_stripped() -> (
    None
):
    plain = (
        "for $p < 0.05$ and $q > 0.1$ the error is small in every one of the settings. "
        * 2
    )
    marked = f"<jats:p>We use <jats:italic>k</jats:italic>-nearest neighbours. {LONG}</jats:p>"
    for text, expected in (
        (plain, plain.strip()),
        (marked, f"We use k-nearest neighbours. {LONG}"),
    ):
        payload = json.loads(openalex_work())
        index: dict[str, list[int]] = {}
        for position, word in enumerate(text.split()):
            index.setdefault(word, []).append(position)
        payload["abstract_inverted_index"] = index
        parsed = parse_openalex_work(json.dumps(payload), matched_by="doi")
        assert parsed is not None
        assert parsed.text.split() == expected.split()


def test_a_malformed_openalex_index_is_ignored_not_a_crash() -> None:
    assert deinvert("not a mapping") == ""
    assert deinvert({"a": "x", "b": [0, "y", None], 3: [1]}) == "b"


def test_hidden_character_check_matches_the_sites_rule() -> None:
    samples = [
        "a",
        "a\nb",
        "a\u200bb",
        "a\u2060b",
        "a\u00adb",
        "a\U000e0041b",
        "a b",
        "日本語",
        "a" + chr(0xD835) + "b",
        "a\u2028b",
    ]
    assert [has_hidden_character(t) for t in samples] == [
        has_control_character(t) for t in samples
    ]


def test_the_tool_and_the_site_agree_on_what_a_line_may_say() -> None:
    assert abstract_parsing.SOURCES == ABSTRACT_SOURCES
    assert abstract_parsing.MATCHES == ABSTRACT_MATCHES
    assert abstract_parsing.MAX_ABSTRACT_CHARS == MAX_ABSTRACT_CHARS


# --- who wrote it, what kind of record it is ------------------------------------------


def title_hit(**fields: object):
    return found("Towards Open Set Deep Networks", year=2016, how="title", **fields)  # type: ignore[arg-type]


def test_a_title_match_needs_an_author_in_common() -> None:
    r = row(authors_surnames="Bendale; Boult")
    assert accept(r, title_hit(authors=("Terrance E. Boult",)))
    assert not accept(r, title_hit(authors=("Someone Else", "Another Person")))
    assert not accept(r, title_hit(authors=()))  # the source does not say who wrote it


def test_a_method_with_no_recorded_authors_cannot_be_matched_by_title() -> None:
    assert not accept(row(authors_surnames=""), title_hit())
    assert accept(
        row(authors_surnames=""), found("Towards Open Set Deep Networks")
    )  # by id: fine


@pytest.mark.parametrize(
    ("surnames", "authors"),
    [
        ("Mendes Júnior; de Souza", ("Pedro Ribeiro Mendes Junior",)),  # accents
        ("de Rezende Rocha", ("Anderson Rocha",)),  # particles in the recorded surname
        ("An", ("Jinwon An", "Sungzoon Cho")),
    ],
)
def test_author_names_are_compared_without_accents_or_particles(
    surnames: str, authors: tuple[str, ...]
) -> None:
    assert accept(row(authors_surnames=surnames), title_hit(authors=authors))


def test_a_surname_is_a_whole_word_not_a_piece_of_one() -> None:
    assert not accept(
        row(authors_surnames="An"), title_hit(authors=("Daniel Anderson",))
    )


@pytest.mark.parametrize(
    "kind",
    [
        "article",
        "preprint",
        "book-chapter",
        "review",
        "conference-paper",
        "proceedings-article",
        "journal-article",
        "",
    ],
)
def test_a_title_match_may_be_a_paper(kind: str) -> None:
    assert accept(row(), title_hit(kind=kind))


@pytest.mark.parametrize(
    "kind", ["dataset", "peer-review", "paratext", "erratum", "other"]
)
def test_a_title_match_may_not_be_a_dataset_or_a_review_of_it(kind: str) -> None:
    assert not accept(row(), title_hit(kind=kind))


def test_a_title_match_with_another_doi_is_another_record_unless_it_is_a_preprint() -> (
    None
):
    r = row(doi="10.1007/S10994-016-5610-8")
    assert accept(
        r, title_hit(kind="article", doi="10.1007/s10994-016-5610-8")
    )  # same, any case
    assert not accept(r, title_hit(kind="article", doi="10.6084/m9.figshare.1097614"))
    assert accept(r, title_hit(kind="preprint", doi="10.48550/arxiv.1511.06233"))
    assert accept(row(doi=""), title_hit(kind="article", doi="10.6084/m9.figshare.1"))


def test_the_look_alike_dataset_record_with_the_papers_own_authors_is_rejected() -> (
    None
):
    """A real case: OpenAlex has the paper's figshare dataset under the same title."""
    r = row(
        title="Nearest Neighbors Distance Ratio Open-Set Classifier",
        year="2017",
        authors_surnames="Mendes Júnior; de Souza; Werneck; Rocha",
        doi="10.1007/s10994-016-5610-8",
    )
    dataset = found(
        "Nearest neighbors distance ratio open-set classifier",
        year=2014,
        how="title",
        kind="dataset",
        doi="10.6084/m9.figshare.1097614",
        authors=("Pedro Ribeiro Mendes Júnior", "Roberto Medeiros de Souza"),
    )
    assert not accept(r, dataset)


# --- damaged text ---------------------------------------------------------------------


@pytest.mark.parametrize("lone", [chr(0xD835), chr(0xDC00)])
def test_a_lone_surrogate_never_reaches_the_file(lone: str) -> None:
    cleaned = clean_abstract(f"{LONG[:50]}{lone}{LONG[50:]}", markup=False)
    assert lone not in cleaned
    cleaned.encode("utf-8")  # must not raise
    assert has_hidden_character(lone)


def test_an_abstract_with_a_replacement_character_is_refused_as_damaged() -> None:
    assert clean_abstract(f"{LONG} caf\ufffd and more words") == ""


def test_an_abstract_that_is_too_long_is_refused_not_cut() -> None:
    assert clean_abstract("word " * 2000, markup=False) == ""  # 10000 characters
    assert clean_abstract("word " * 1500, markup=False) != ""  # 7500: fine


def test_titles_are_cleaned_of_surrogates_too() -> None:
    payload = json.loads(openalex_work())
    payload["title"] = "Toward\ud835 Open Set Recognition"
    parsed = parse_openalex_work(json.dumps(payload), matched_by="doi")
    assert parsed is not None
    parsed.title.encode("utf-8")


# --- authors, kind and DOI are read from the sources ----------------------------------


def test_openalex_gives_authors_kind_and_doi() -> None:
    parsed = parse_openalex_work(
        openalex_work(kind="dataset", doi="https://doi.org/10.6084/M9.X"),
        matched_by="title",
    )
    assert parsed is not None
    assert parsed.authors == ("Abhijit Bendale", "Terrance E. Boult")
    assert parsed.kind == "dataset"
    assert parsed.doi == "10.6084/m9.x"  # no prefix, lower case


def test_openalex_odd_authorships_are_ignored() -> None:
    payload = json.loads(openalex_work())
    payload["authorships"] = [
        {"author": None},
        {"author": {"display_name": None}},
        "x",
        {"author": {"display_name": "Ok Name"}},
    ]
    parsed = parse_openalex_work(json.dumps(payload), matched_by="title")
    assert parsed is not None
    assert parsed.authors == ("Ok Name",)
    payload["authorships"] = "not a list"
    parsed = parse_openalex_work(json.dumps(payload), matched_by="title")
    assert parsed is not None
    assert parsed.authors == ()


def test_arxiv_gives_the_authors() -> None:
    entry = parse_arxiv_atom(ATOM)["1506.06112"]
    assert entry.authors == ("Ethan M. Rudd", "Walter J. Scheirer", "Terrance E. Boult")


# --- an identifier with a somewhat different title ------------------------------------


GANS = "Unsupervised Anomaly Detection with GANs to Guide Marker Discovery"
GENERATIVE = "Unsupervised Anomaly Detection with Generative Adversarial Networks to Guide Marker Discovery"


def test_an_id_match_with_a_spelled_out_title_is_accepted_if_an_author_is_shared() -> (
    None
):
    """A real case: the methods file says GANs, arXiv spells the words out."""
    r = row(title=GANS, authors_surnames="Schlegl; Seeböck")
    ours = found(
        GENERATIVE, how="arxiv id", authors=("Thomas Schlegl", "Philipp Seeböck")
    )
    assert (
        0.75 <= title_similarity(GANS, GENERATIVE) < 0.9
    )  # too far apart for the title alone
    assert accept(r, ours)


def test_an_id_match_with_a_somewhat_different_title_and_no_shared_author_is_rejected() -> (
    None
):
    r = row(title=GANS, authors_surnames="Schlegl; Seeböck")
    assert not accept(r, found(GENERATIVE, how="arxiv id", authors=("Someone Else",)))
    assert not accept(
        r, found(GENERATIVE, how="arxiv id", authors=())
    )  # Crossref, CVF, PMLR


def test_a_shared_author_does_not_excuse_a_different_paper_behind_the_identifier() -> (
    None
):
    """The link of CPN in the methods file leads to another paper of the same group."""
    r = row(
        title="Convolutional Prototype Network for Open Set Recognition",
        authors_surnames="Yang; Zhang; Yin; Liu",
    )
    other = found(
        "Unified Classification and Rejection: A One-versus-All Framework",
        how="arxiv id",
        authors=("Zhen Cheng", "Xu-Yao Zhang", "Cheng-Lin Liu"),
    )
    assert not accept(r, other)


def test_a_fuzzy_id_match_needs_the_first_author_not_just_any_author() -> None:
    """Siblings by the same group share an author: Boult is on both of these papers."""
    r = row(
        title="Toward Open Set Recognition",
        authors_surnames="Scheirer; de Rezende Rocha; Boult",
    )
    sibling = found(
        "Towards Open World Recognition",
        how="arxiv id",
        authors=("Abhijit Bendale", "Terrance E. Boult"),
    )
    assert 0.75 <= title_similarity(r["title"], sibling.title) < 0.9
    assert not accept(r, sibling)


def test_the_first_author_may_be_listed_with_a_middle_name_or_accents() -> None:
    r = row(title=GANS, authors_surnames="Seeböck; Schlegl")
    assert accept(
        r,
        found(
            GENERATIVE, how="arxiv id", authors=("Philipp Seebock", "Thomas Schlegl")
        ),
    )
    assert not accept(
        r,
        found(
            GENERATIVE, how="arxiv id", authors=("Thomas Schlegl", "Philipp Seeböck")
        ),
    )


def test_no_two_methods_of_the_collection_match_each_other_by_title_either(
    methods: pd.DataFrame,
) -> None:
    rows = methods.to_dict(orient="records")
    clashes = [
        (a["id"], b["id"])
        for a in rows
        for b in rows
        if a["id"] != b["id"]
        and accept(
            a,
            found(
                b["title"],
                year=int(a["year"]),
                how="title",
                authors=_surnames(b),
                kind="article",
            ),
        )
    ]
    assert clashes == []


# --- hostile text from a source -------------------------------------------------------


def test_a_huge_unclosed_tag_run_is_refused_quickly_not_chewed_for_minutes() -> None:
    import time

    started = time.perf_counter()
    assert clean_abstract("<title>" * 40_000) == ""
    assert clean_abstract('<div id="abstract">' * 40_000) == ""
    assert (
        time.perf_counter() - started < 3.0
    )  # it takes about 0.1 s; quadratic took minutes


def test_markup_longer_than_any_real_abstract_is_refused() -> None:
    long_markup = "<i></i>" * 8000 + LONG
    assert len(long_markup) > MAX_RAW_CHARS
    assert clean_abstract(long_markup) == ""
    assert clean_abstract(f"<i>{LONG}</i>") == LONG  # ordinary markup is fine


def test_only_the_top_of_a_paper_page_is_read() -> None:
    url = "https://proceedings.mlr.press/v199/x.html"
    page = (
        "<h1>A Title</h1>" + " " * MAX_PAGE_CHARS + f'<div id="abstract">{LONG}</div>'
    )
    assert parse_pmlr(page, url) is None


# --- one rule for the link of a line --------------------------------------------------


@pytest.mark.parametrize(
    ("source", "url"),
    [
        ("arXiv", "https://arxiv.org/abs/1511.06233"),
        ("OpenAlex", "https://openalex.org/W2119880843"),
        ("OpenAlex", "https://doi.org/10.1109/tpami.2012.256"),
        ("Crossref", "https://doi.org/10.1/x"),
        ("CVF", "https://openaccess.thecvf.com/content/CVPR2021/html/x.html"),
        ("PMLR", "https://proceedings.mlr.press/v199/x.html"),
        ("Manual", "https://example.org/a/page?x=1#top"),
        ("Manual", "http://example.org/p"),
    ],
)
def test_a_link_that_belongs_to_its_source_is_fine(source: str, url: str) -> None:
    assert url_problem(source, url) == ""


@pytest.mark.parametrize(
    ("source", "url"),
    [
        (
            "arXiv",
            f"https://arxiv.org{AT}evil.example/abs/1",
        ),  # the host is evil.example
        ("arXiv", f"https://user:pw{AT}arxiv.org/abs/1"),
        ("arXiv", "http://arxiv.org/abs/1"),  # a find must be https
        ("arXiv", "https://evil.example/arxiv.org/abs/1"),
        ("arXiv", "https://arxiv.org.evil.example/abs/1"),
        ("arXiv", "https://openalex.org/W1"),  # another source's site
        ("arXiv", "https://arxiv.org:8443/abs/1"),
        ("OpenAlex", "https://evil.example/W1"),
        ("CVF", "https://arxiv.org/abs/1"),
        ("Manual", "https:///x"),
        ("Manual", "https://?x"),
        ("Manual", "https://#"),
        ("Manual", f"https://user{AT}example.org/p"),
        ("Manual", "javascript:alert(1)"),
        ("Manual", "https://example.org/a b"),
        ("Manual", "https://example.org:notaport/p"),
        ("Manual", "https://example.org/" + "a" * MAX_URL_CHARS),
        ("Manual", ""),
    ],
)
def test_a_link_that_is_not_the_sources_own_is_a_problem(source: str, url: str) -> None:
    assert url_problem(source, url)


def test_the_tool_and_the_site_agree_on_the_link_of_each_source() -> None:
    from explorer.constants import ABSTRACT_SOURCE_HOSTS, MAX_ABSTRACT_URL_CHARS

    assert abstract_parsing.SOURCE_HOSTS == ABSTRACT_SOURCE_HOSTS
    assert abstract_parsing.MAX_URL_CHARS == MAX_ABSTRACT_URL_CHARS
