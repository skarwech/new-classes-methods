"""CSV download of the filtered rows."""

from __future__ import annotations

import pandas as pd

from .constants import ABSTRACT_FIELDS, PUBLIC_COLUMNS

# A spreadsheet runs a cell that starts with one of these as a formula.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def _defuse(text: str) -> str:
    """Show text that would be run as a formula as text: lead it with a quote."""
    return "'" + text if text.startswith(_FORMULA_STARTS) else text


def csv_bytes(frame: pd.DataFrame) -> bytes:
    """The public columns of ``frame``, and its abstract fields if any, as UTF-8 CSV.

    A byte-order mark leads the file so that spreadsheet programs read accents
    correctly; helper columns of the table are never included. A cell that opens like a
    formula (abstracts are text from third parties) is led by a quote.
    """
    columns = [
        name for name in (*PUBLIC_COLUMNS, *ABSTRACT_FIELDS) if name in frame.columns
    ]
    shown = frame.loc[:, columns]
    safe = shown.assign(**{name: shown[name].map(_defuse) for name in columns})
    return safe.to_csv(index=False, lineterminator="\n").encode("utf-8-sig")
