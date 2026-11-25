"""Search and filters over the methods table."""

from __future__ import annotations

import json
import operator
from collections.abc import Iterable
from dataclasses import dataclass
from functools import reduce

import pandas as pd

from .constants import MAX_QUERY_CHARS
from .textfold import fold

YearRange = tuple[int, int]


@dataclass(frozen=True)
class Filters:
    """What the visitor typed and chose in the sidebar; empty means "no filter"."""

    query: str = ""
    families: tuple[str, ...] = ()
    code_types: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    year_range: YearRange | None = None

    @classmethod
    def from_inputs(
        cls,
        *,
        query: str = "",
        families: Iterable[str] = (),
        code_types: Iterable[str] = (),
        checks: Iterable[str] = (),
        year_range: YearRange | None = None,
        year_bounds: YearRange | None = None,
    ) -> Filters:
        """Normalize widget values: tidy text, sorted choices, full span = no filter."""
        narrowed: YearRange | None = None
        if year_range is not None:
            low, high = sorted(year_range)
            if (low, high) != (tuple(sorted(year_bounds)) if year_bounds else None):
                narrowed = (low, high)
        return cls(
            query=" ".join(query.split())[:MAX_QUERY_CHARS],
            families=tuple(sorted(set(families))),
            code_types=tuple(sorted(set(code_types))),
            checks=tuple(sorted(set(checks))),
            year_range=narrowed,
        )

    def is_active(self) -> bool:
        """True when any filter narrows the list."""
        return bool(
            fold(self.query)
            or self.families
            or self.code_types
            or self.checks
            or self.year_range is not None
        )

    def signature(self) -> str:
        """A stable text, equal exactly when two filter sets select the same rows."""
        payload = {
            "q": fold(self.query),
            "f": list(self.families),
            "c": list(self.code_types),
            "k": list(self.checks),
            "y": list(self.year_range) if self.year_range is not None else None,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def year_bounds(frame: pd.DataFrame) -> YearRange:
    """Earliest and latest year in the table."""
    return int(frame["year_num"].min()), int(frame["year_num"].max())


def apply_filters(frame: pd.DataFrame, filters: Filters) -> pd.DataFrame:
    """The rows that pass every filter, in file order. The input is not modified."""
    masks = [
        frame["search_text"].str.contains(token, regex=False)
        for token in fold(filters.query).split()
    ]
    if filters.families:
        masks.append(frame["tree_family"].isin(filters.families))
    if filters.code_types:
        masks.append(frame["code_type"].isin(filters.code_types))
    if filters.checks:
        masks.append(frame["check"].isin(filters.checks))
    if filters.year_range is not None:
        low, high = filters.year_range
        masks.append(frame["year_num"].between(low, high))
    keep = reduce(operator.and_, masks, pd.Series(True, index=frame.index))
    return frame.loc[keep]
