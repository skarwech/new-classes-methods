"""Load, validate and prepare the public methods table."""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from .constants import (
    AUTHORS_COMPLETE_VALUES,
    CHECK_VALUES,
    CODE_TYPES,
    PUBLIC_COLUMNS,
)
from .links import is_http_url, parse_code_alt
from .textfold import fold

MAX_REPORTED_PROBLEMS = 10

_LOG = logging.getLogger(__name__)

_ID = re.compile(r"[A-Za-z0-9_.\-]{1,32}")
_YEAR = re.compile(r"[0-9]{4}")
_REQUIRED_TEXT = ("id", "tree_family", "tree_section", "method", "year")
_URL_COLUMNS = ("paper_url", "code_url")

# Text that is shown as markdown. Line breaks and invisible or direction-changing
# characters would change the layout of the card; the patterns below would be turned
# into links or emoji by the markdown renderer. (Real data has none of them.)
_TEXT_COLUMNS = ("method", "authors_surnames", "title", "venue")
_CONTROL = re.compile(
    r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]"
)
_RISKY_TEXT = (
    (
        re.compile(r"://|\bwww\.", re.IGNORECASE),
        "a web address (links belong in paper_url or code_url)",
    ),
    (re.compile(r"@"), "an @ sign (it would become an e-mail link)"),
    (
        re.compile(r":[A-Za-z0-9_+\-/]+:"),
        "a :name: pattern (it would render as an emoji)",
    ),
)


class DataError(ValueError):
    """The public CSV is missing, malformed or inconsistent."""


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError as error:
        _LOG.error("data file not found: %s", path)
        raise DataError(f"data file not found: {path.name}") from error
    except OSError as error:
        _LOG.error("data file could not be read: %s (%s)", path, error)
        reason = type(error).__name__
        raise DataError(
            f"data file could not be read: {path.name} ({reason})"
        ) from error


def _read(path: Path) -> pd.DataFrame:
    """Read every column as text; the strings "NA" or "None" stay text."""
    raw = _read_bytes(path)
    if b"\x00" in raw:  # some pandas versions cut a cell at a NUL byte, silently
        raise DataError(f"data file contains a NUL byte: {path.name}")
    try:
        return pd.read_csv(
            io.BytesIO(raw), dtype=str, keep_default_na=False, encoding="utf-8-sig"
        )
    except (
        pd.errors.ParserError,
        pd.errors.EmptyDataError,
        UnicodeDecodeError,
    ) as error:
        _LOG.error("data file could not be read: %s (%s)", path, error)
        reason = type(error).__name__
        raise DataError(
            f"data file could not be read: {path.name} ({reason})"
        ) from error


def _code_problems(row: Mapping[str, str]) -> list[str]:
    problems: list[str] = []
    code_type, code_url, code_alt = row["code_type"], row["code_url"], row["code_alt"]
    if code_type in CODE_TYPES:
        if code_type == "none" and code_url:
            problems.append("code_type is 'none' but code_url is set")
        if code_type != "none" and not code_url:
            problems.append(f"code_type is {code_type!r} but code_url is empty")
        if code_type == "none" and code_alt:
            problems.append(
                "code_alt needs a primary code link, but code_type is 'none'"
            )
    if code_alt:
        try:
            parse_code_alt(code_alt)
        except ValueError as error:
            problems.append(f"code_alt: {error}")
    return problems


def _text_problems(row: Mapping[str, str]) -> list[str]:
    problems: list[str] = []
    for name in PUBLIC_COLUMNS:
        if _CONTROL.search(row[name]):
            problems.append(f"{name} contains a line break or control character")
    for name in _TEXT_COLUMNS:
        problems += [
            f"{name} contains {reason}"
            for pattern, reason in _RISKY_TEXT
            if pattern.search(row[name])
        ]
    return problems


def _cell_problems(row: Mapping[str, str]) -> list[str]:
    problems: list[str] = []
    problems += [f"{name} is empty" for name in _REQUIRED_TEXT if not row[name].strip()]
    if row["id"].strip() and not _ID.fullmatch(row["id"]):
        problems.append(
            f"id {row['id']!r} is not 1 to 32 letters, digits, '.', '_' or '-'"
        )
    if row["year"].strip() and not _YEAR.fullmatch(row["year"]):
        problems.append(f"year {row['year']!r} is not a four-digit year")
    if row["code_type"] not in CODE_TYPES:
        problems.append(
            f"code_type {row['code_type']!r} is not one of {list(CODE_TYPES)}"
        )
    if row["check"] not in CHECK_VALUES:
        problems.append(f"check {row['check']!r} is not one of {list(CHECK_VALUES)}")
    if row["authors_complete"] not in AUTHORS_COMPLETE_VALUES:
        problems.append(
            f"authors_complete {row['authors_complete']!r} is not one of "
            f"{list(AUTHORS_COMPLETE_VALUES)}"
        )
    for name in _URL_COLUMNS:
        if row[name] and not is_http_url(row[name]):
            problems.append(f"{name} {row[name]!r} is not an http(s) link")
    padded = [name for name in PUBLIC_COLUMNS if row[name] != row[name].strip()]
    if padded:
        problems.append(f"leading or trailing whitespace in {padded}")
    return problems + _text_problems(row)


def _row_problems(position: int, row: Mapping[str, str]) -> list[str]:
    label = f"id {row['id']!r}" if row["id"].strip() else f"row {position}"
    return [f"{label}: {text}" for text in _cell_problems(row) + _code_problems(row)]


def _collect_problems(frame: pd.DataFrame) -> list[str]:
    problems: list[str] = []
    for position, row in enumerate(frame.to_dict(orient="records"), start=1):
        problems += _row_problems(position, row)
    duplicates = sorted(frame.loc[frame["id"].duplicated(keep=False), "id"].unique())
    if duplicates:
        problems.append(f"duplicate ids: {duplicates}")
    return problems


def _format_problems(problems: list[str]) -> str:
    shown = problems[:MAX_REPORTED_PROBLEMS]
    lines = [
        f"The public CSV has {len(problems)} problem(s):",
        *(f"  - {text}" for text in shown),
    ]
    hidden = len(problems) - len(shown)
    if hidden > 0:
        lines.append(f"  ... and {hidden} more")
    return "\n".join(lines)


def prepare_methods(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a new frame: the public columns plus ``year_num`` and ``search_text``.

    ``search_text`` is the folded method name, authors and title, which is what the
    search box looks at. The input frame is left untouched.
    """
    base = frame.loc[:, list(PUBLIC_COLUMNS)].reset_index(drop=True)
    authors = base["authors_surnames"].str.replace(";", " ", regex=False)
    haystack = base["method"] + " " + authors + " " + base["title"]
    return base.assign(
        year_num=base["year"].astype(int),
        search_text=haystack.map(fold),
    )


def load_methods(path: str | Path) -> pd.DataFrame:
    """Read, validate and prepare the public CSV; raise ``DataError`` if unusable."""
    frame = _read(Path(path))
    missing = [name for name in PUBLIC_COLUMNS if name not in frame.columns]
    if missing:
        raise DataError(f"data file is missing columns: {missing}")
    if frame.empty:
        raise DataError(f"data file has no rows: {Path(path).name}")
    problems = _collect_problems(frame)
    if problems:
        raise DataError(_format_problems(problems))
    return prepare_methods(frame)
