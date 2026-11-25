"""Shared fixtures: the real public CSV and a small builder for synthetic rows."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from explorer.constants import PUBLIC_COLUMNS

SITE_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = SITE_ROOT / "data" / "methods_public.csv"

_DEFAULT_ROW = {
    "id": "1",
    "tree_family": "Unknown Rejection",
    "tree_section": "1.1 Discriminative Open Set Recognition",
    "tree_type": "",
    "method": "Method",
    "year": "2020",
    "authors_surnames": "Doe; Roe",
    "authors_complete": "yes",
    "title": "A Title",
    "venue": "A Venue 2020",
    "doi": "",
    "arxiv": "",
    "paper_url": "",
    "code_url": "",
    "code_type": "none",
    "code_alt": "",
    "check": "V",
}


def make_row(**overrides: str) -> dict[str, str]:
    """One synthetic CSV row (all 17 public columns, as text)."""
    unknown = set(overrides) - set(PUBLIC_COLUMNS)
    if unknown:
        raise KeyError(f"unknown columns: {sorted(unknown)}")
    return {**_DEFAULT_ROW, **overrides}


def make_raw_frame(*rows: dict[str, str]) -> pd.DataFrame:
    """A raw (unprepared) frame from synthetic rows."""
    return pd.DataFrame(list(rows), columns=list(PUBLIC_COLUMNS), dtype=str)


def make_frame(*rows: dict[str, str]) -> pd.DataFrame:
    """A prepared frame (derived columns added) from synthetic rows."""
    from explorer.data import prepare_methods

    return prepare_methods(make_raw_frame(*rows))


def write_csv(path: Path, *rows: dict[str, str], bom: bool = True) -> Path:
    make_raw_frame(*rows).to_csv(
        path, index=False, encoding="utf-8-sig" if bom else "utf-8"
    )
    return path


@pytest.fixture(scope="session")
def methods() -> pd.DataFrame:
    """The real, prepared public table."""
    from explorer.data import load_methods

    return load_methods(CSV_PATH)
