"""CSV download of the filtered rows."""

from __future__ import annotations

import pandas as pd

from .constants import PUBLIC_COLUMNS


def csv_bytes(frame: pd.DataFrame) -> bytes:
    """The public columns of ``frame`` as UTF-8 CSV.

    A byte-order mark leads the file so that spreadsheet programs read accents
    correctly; helper columns of the table are never included.
    """
    text = frame.loc[:, list(PUBLIC_COLUMNS)].to_csv(index=False, lineterminator="\n")
    return text.encode("utf-8-sig")
