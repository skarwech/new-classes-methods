"""Snapshot of the shipped public CSV: the counts the site is built to handle.

These numbers describe ``data/methods_public.csv`` as delivered. When the CSV is regenerated
with more or fewer methods, update them here (the app itself never hard-codes a count).
"""

from __future__ import annotations

import unicodedata

import pandas as pd
import pytest

from explorer.textfold import fold
from tests.wording import PUBLIC_DATA_WORDING

pytestmark = pytest.mark.unit


def test_row_count_and_unique_ids(methods: pd.DataFrame) -> None:
    assert len(methods) == 170
    assert methods["id"].is_unique


def test_ids_are_the_numbers_1_to_162_and_the_eight_additions(
    methods: pd.DataFrame,
) -> None:
    ids = methods["id"].tolist()
    assert sorted(i for i in ids if i.isdigit()) == sorted(
        str(n) for n in range(1, 163)
    )
    assert sorted(i for i in ids if not i.isdigit()) == [f"N{n}" for n in range(1, 9)]


def test_family_sizes(methods: pd.DataFrame) -> None:
    sizes = methods["tree_family"].value_counts().to_dict()
    assert sizes == {
        "Unknown Rejection": 63,
        "Class Discovery": 31,
        "Model Integration": 23,
        "Stream Adaptation": 43,
        "Pipeline component references": 10,
    }


def test_code_availability_counts(methods: pd.DataFrame) -> None:
    by_type = methods["code_type"].value_counts().to_dict()
    assert by_type == {"official": 105, "none": 40, "library": 19, "third-party": 6}
    assert (methods["code_url"] != "").sum() == 130
    assert (methods["code_alt"] != "").sum() == 52


def test_reference_check_values(methods: pd.DataFrame) -> None:
    assert set(methods["check"]) == {"V", "C", "C?"}


def test_papers_without_a_link(methods: pd.DataFrame) -> None:
    missing = methods[methods["paper_url"] == ""]
    assert len(missing) == 47
    assert (missing["doi"] == "").all()
    assert (missing["arxiv"] == "").all()


def test_author_list_edge_cases(methods: pd.DataFrame) -> None:
    assert (methods["authors_complete"] == "no").sum() == 4
    no_authors = methods[methods["authors_surnames"] == ""]
    assert no_authors["method"].tolist() == ["ALSET"]


def test_year_span(methods: pd.DataFrame) -> None:
    assert (methods["year_num"].min(), methods["year_num"].max()) == (1954, 2026)


def _has_accent(text: str) -> bool:
    return any(unicodedata.combining(ch) for ch in unicodedata.normalize("NFKD", text))


def test_accent_folding_matters_for_24_rows(methods: pd.DataFrame) -> None:
    text = (
        methods["method"] + " " + methods["authors_surnames"] + " " + methods["title"]
    )
    accented = text[text.map(_has_accent)]
    assert len(accented) == 24
    # Every accent in the shipped data folds to plain ASCII (the Greek mu is left as it is).
    assert all(fold(value).replace("μ", "").isascii() for value in accented)


def test_public_columns_contain_no_working_wording(methods: pd.DataFrame) -> None:
    from explorer.constants import PUBLIC_COLUMNS

    for column in PUBLIC_COLUMNS:
        hits = methods[column].map(
            lambda value: bool(PUBLIC_DATA_WORDING.search(value))
        )
        assert not hits.any(), (column, methods.loc[hits, "id"].tolist())


def test_no_cell_can_be_read_as_a_spreadsheet_formula(methods: pd.DataFrame) -> None:
    from explorer.constants import PUBLIC_COLUMNS

    for column in PUBLIC_COLUMNS:
        assert not methods[column].str.match(r"^[=+\-@\t\r]").any(), column
