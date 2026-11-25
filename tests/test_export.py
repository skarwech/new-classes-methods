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
