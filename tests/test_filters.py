"""Search and filters over the methods table."""

from __future__ import annotations

import pandas as pd
import pytest

from explorer.constants import MAX_QUERY_CHARS
from explorer.filters import Filters, apply_filters, year_bounds
from explorer.textfold import fold
from tests.conftest import make_frame, make_row

pytestmark = pytest.mark.unit


def ids(frame: pd.DataFrame) -> list[str]:
    return frame["id"].tolist()


# --- defaults -------------------------------------------------------------------------


def test_default_filters_are_inactive_and_keep_every_row(methods: pd.DataFrame) -> None:
    filters = Filters()
    assert not filters.is_active()
    result = apply_filters(methods, filters)
    assert ids(result) == ids(methods)
    assert result is not methods


def test_year_bounds_come_from_the_data(methods: pd.DataFrame) -> None:
    assert year_bounds(methods) == (1954, 2026)


# --- search ---------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["halasz", "HALASZ", "Halász", "  halász  "])
def test_search_ignores_accents_case_and_padding(
    methods: pd.DataFrame, query: str
) -> None:
    assert ids(apply_filters(methods, Filters(query=query))) == ["N3", "N4"]


@pytest.mark.parametrize("query", ["candes", "Candès"])
def test_search_finds_the_single_candes_row(methods: pd.DataFrame, query: str) -> None:
    assert ids(apply_filters(methods, Filters(query=query))) == ["155"]


def test_search_covers_method_authors_and_title(methods: pd.DataFrame) -> None:
    assert "4" in ids(apply_filters(methods, Filters(query="openmax")))  # method
    assert {"1", "2", "3"} <= set(
        ids(apply_filters(methods, Filters(query="scheirer")))
    )  # authors
    assert "5" in ids(
        apply_filters(methods, Filters(query="extreme value machine"))
    )  # title


def test_search_does_not_look_at_venue_or_doi() -> None:
    frame = make_frame(
        make_row(venue="SECRETVENUE", doi="10.1/secretdoi", arxiv="9999.99999")
    )
    for needle in ("secretvenue", "secretdoi", "9999.99999"):
        assert apply_filters(frame, Filters(query=needle)).empty


def test_search_words_are_anded(methods: pd.DataFrame) -> None:
    assert ids(apply_filters(methods, Filters(query="halasz fake"))) == ["N4"]
    assert apply_filters(methods, Filters(query="halasz zzzzqqqq")).empty


@pytest.mark.parametrize(
    "query", ["(", "[a-", ".*", "\\", "a|b", "+", "?", "$", "^", "(?i)"]
)
def test_search_never_fails_on_regex_characters(
    methods: pd.DataFrame, query: str
) -> None:
    result = apply_filters(methods, Filters(query=query))  # must not raise
    words = fold(query).split()
    assert all(all(word in text for word in words) for text in result["search_text"])


def test_regex_wildcards_are_literal_text(methods: pd.DataFrame) -> None:
    assert apply_filters(methods, Filters(query=".*")).empty


def test_search_ignores_punctuation_between_words(methods: pd.DataFrame) -> None:
    def found(query: str) -> list[str]:
        return ids(apply_filters(methods, Filters(query=query)))

    assert found("Bendale, Boult") == found("Bendale Boult") != []
    assert found("Scheirer, Boult") == found("Scheirer Boult") != []
    assert found("open-set") == found("open set") != []
    assert found("time series") == found("time-series") != []
    assert found("class-incremental") == found("class incremental") != []


def test_a_query_of_only_punctuation_filters_nothing(methods: pd.DataFrame) -> None:
    filters = Filters.from_inputs(query=" (,) - ")
    assert not filters.is_active()
    assert len(apply_filters(methods, filters)) == len(methods)


def test_whitespace_only_query_changes_nothing(methods: pd.DataFrame) -> None:
    filters = Filters.from_inputs(query="   \t ")
    assert not filters.is_active()
    assert len(apply_filters(methods, filters)) == len(methods)


# --- the other filters ----------------------------------------------------------------


def test_family_filter(methods: pd.DataFrame) -> None:
    one = apply_filters(methods, Filters(families=("Unknown Rejection",)))
    assert len(one) == 63
    two = apply_filters(
        methods, Filters(families=("Unknown Rejection", "Class Discovery"))
    )
    assert len(two) == 94


def test_code_type_filter(methods: pd.DataFrame) -> None:
    assert len(apply_filters(methods, Filters(code_types=("none",)))) == 40
    assert (
        len(apply_filters(methods, Filters(code_types=("official", "library")))) == 124
    )


def test_reference_check_filter(methods: pd.DataFrame) -> None:
    assert len(apply_filters(methods, Filters(checks=("C?",)))) == 8


def test_year_range_is_inclusive(methods: pd.DataFrame) -> None:
    result = apply_filters(methods, Filters(year_range=(2013, 2014)))
    assert set(result["year_num"]) <= {2013, 2014}
    assert {"1", "2", "3"} <= set(
        ids(result)
    )  # 1-vs-Set (2013), W-SVM (2014), PI-SVM (2014)


def test_filters_combine_with_and(methods: pd.DataFrame) -> None:
    filters = Filters(
        query="halasz",
        families=("Unknown Rejection",),
        checks=("V",),
        year_range=(2023, 2023),
    )
    assert ids(apply_filters(methods, filters)) == ["N3", "N4"]
    narrower = Filters(query="halasz", families=("Class Discovery",))
    assert apply_filters(methods, narrower).empty


def test_empty_result_keeps_the_columns(methods: pd.DataFrame) -> None:
    result = apply_filters(methods, Filters(query="zzzzqqqq"))
    assert result.empty
    assert list(result.columns) == list(methods.columns)


def test_apply_filters_does_not_mutate_its_input(methods: pd.DataFrame) -> None:
    before = methods.copy(deep=True)
    apply_filters(methods, Filters(query="halasz", families=("Unknown Rejection",)))
    assert methods.equals(before)


def test_filtered_rows_keep_the_file_order(methods: pd.DataFrame) -> None:
    result = apply_filters(
        methods, Filters(families=("Stream Adaptation", "Unknown Rejection"))
    )
    positions = {value: index for index, value in enumerate(ids(methods))}
    ordered = [positions[value] for value in ids(result)]
    assert ordered == sorted(ordered)


# --- normalization and signature ------------------------------------------------------


def test_from_inputs_sorts_and_deduplicates_choices() -> None:
    filters = Filters.from_inputs(
        families=["b", "a", "a"], code_types=["official", "none"], checks=["V", "C"]
    )
    assert filters.families == ("a", "b")
    assert filters.code_types == ("none", "official")
    assert filters.checks == ("C", "V")


def test_from_inputs_treats_the_full_year_span_as_no_filter() -> None:
    full = Filters.from_inputs(year_range=(1954, 2026), year_bounds=(1954, 2026))
    assert full.year_range is None
    assert not full.is_active()
    narrowed = Filters.from_inputs(year_range=(1990, 2026), year_bounds=(1954, 2026))
    assert narrowed.year_range == (1990, 2026)
    assert narrowed.is_active()


def test_from_inputs_trims_collapses_and_caps_the_query() -> None:
    assert Filters.from_inputs(query="  open \t set  ").query == "open set"
    long_query = Filters.from_inputs(query="x" * (MAX_QUERY_CHARS + 50)).query
    assert len(long_query) == MAX_QUERY_CHARS


@pytest.mark.parametrize(
    "changed",
    [
        {"query": "a"},
        {"families": ("Unknown Rejection",)},
        {"code_types": ("none",)},
        {"checks": ("V",)},
        {"year_range": (2000, 2010)},
    ],
)
def test_every_filter_makes_the_set_active(changed: dict) -> None:
    assert Filters(**changed).is_active()


def test_signature_is_stable_and_distinguishes_filters() -> None:
    a = Filters(query="halasz", families=("Unknown Rejection",))
    b = Filters(query="halasz", families=("Unknown Rejection",))
    assert a.signature() == b.signature()
    variants = [
        Filters(),
        Filters(query="halasz"),
        Filters(query="halasz", families=("Unknown Rejection",)),
        Filters(families=("Unknown Rejection",)),
        Filters(code_types=("none",)),
        Filters(checks=("none",)),
        Filters(year_range=(2000, 2010)),
        Filters(year_range=(2000, 2011)),
    ]
    assert len({variant.signature() for variant in variants}) == len(variants)


def test_signature_ignores_case_and_accents_in_the_query() -> None:
    assert Filters(query="Halász").signature() == Filters(query="halasz").signature()


def test_a_year_range_without_known_bounds_is_kept() -> None:
    assert Filters.from_inputs(year_range=(1990, 2000)).year_range == (1990, 2000)


def test_a_reversed_year_range_is_put_in_order() -> None:
    assert Filters.from_inputs(year_range=(2000, 1990)).year_range == (1990, 2000)
    full = Filters.from_inputs(year_range=(2026, 1954), year_bounds=(1954, 2026))
    assert full.year_range is None
