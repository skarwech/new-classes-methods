"""Abstracts: read data/abstracts.csv and attach each abstract to its method.

The file is written by ``python -m tools.fetch_abstracts`` (or by hand, with the source
"Manual"). It is optional: without it the methods simply have no abstract.

An abstract is attached by method id. Each line also records the title of the method it
was fetched for; if that no longer matches the methods file (the ids were renumbered, a
title was corrected), that line is left out rather than show the abstract of another
paper. The tool writes one more column, ``source_title`` (what the source calls the
paper); it is for people checking the file and is not read here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

from .constants import (
    ABSTRACT_FIELDS,
    ABSTRACT_MATCHES,
    ABSTRACT_SOURCE_HOSTS,
    ABSTRACT_SOURCES,
    ABSTRACTS_FILE_NAME,
    MAX_ABSTRACT_CHARS,
    MAX_ABSTRACT_URL_CHARS,
)
from .data import (
    ID_PATTERN,
    DataError,
    format_problems,
    has_control_character,
    load_methods,
    read_text_csv,
)
from .shown import show

_LOG = logging.getLogger(__name__)

ABSTRACT_COLUMNS: tuple[str, ...] = ("id", "method_title", *ABSTRACT_FIELDS)
_WHAT = "abstracts file"
MAX_STALE_SHARE = 0.5  # more stale lines than this share: the file is for other methods


def abstracts_path_for(methods_path: str | Path) -> Path:
    """The abstracts file that belongs to a methods file: the same folder."""
    return Path(methods_path).with_name(ABSTRACTS_FILE_NAME)


def _empty() -> pd.DataFrame:
    return pd.DataFrame({name: pd.Series(dtype=str) for name in ABSTRACT_COLUMNS})


def url_problem(source: str, url: str) -> str:
    """Why ``url`` may not be the link of a line from ``source``; "" if it may.

    Any line needs a real http(s) host and no user name; a line from a source other than
    ``Manual`` must be https on that source's own site, so that the label "arXiv" never
    sits on a link to somewhere else. The fetch tool applies the same rule.
    """
    if not url or len(url) > MAX_ABSTRACT_URL_CHARS or any(ch.isspace() for ch in url):
        return "is empty, too long or has a space"
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "is not a link"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "is not an http(s) link"
    if parts.username is not None or parts.password is not None:
        return "has a user name in it"
    hosts = ABSTRACT_SOURCE_HOSTS.get(source)
    if hosts is None:
        return ""
    if (
        parts.scheme != "https"
        or port not in (None, 443)
        or parts.hostname not in hosts
    ):
        return f"is not an https link on {' or '.join(hosts)}, where {source} lives"
    return ""


def _line_problems(row: Mapping[str, str]) -> list[str]:
    problems: list[str] = []
    if not ID_PATTERN.fullmatch(row["id"]):
        problems.append(
            f"id {show(row['id'])} is not 1 to 32 letters, digits, '.', '_' or '-'"
        )
    if not row["method_title"].strip():
        problems.append("method_title is empty")
    text = row["abstract"]
    if not text.strip():
        problems.append("abstract is empty")
    if has_control_character(text):
        problems.append("abstract contains a line break or control character")
    if len(text) > MAX_ABSTRACT_CHARS:
        problems.append(f"abstract is too long (over {MAX_ABSTRACT_CHARS} characters)")
    if row["abstract_source"] not in ABSTRACT_SOURCES:
        problems.append(
            f"abstract_source {show(row['abstract_source'])} is not one of "
            f"{list(ABSTRACT_SOURCES)}"
        )
    if row["abstract_match"] not in ABSTRACT_MATCHES:
        problems.append(
            f"abstract_match {show(row['abstract_match'])} is not one of "
            f"{list(ABSTRACT_MATCHES)}"
        )
    problem = url_problem(row["abstract_source"], row["abstract_url"])
    if problem:
        problems.append(f"abstract_url {show(row['abstract_url'])} {problem}")
    return problems


def load_abstracts(path: str | Path) -> pd.DataFrame:
    """Read and validate an abstracts file; no file means no abstracts."""
    path = Path(path)
    if not path.exists():
        return _empty()
    frame = read_text_csv(path, _WHAT)
    missing = [name for name in ABSTRACT_COLUMNS if name not in frame.columns]
    if missing:
        raise DataError(f"{path.name} is missing columns: {missing}")
    frame = frame.loc[:, list(ABSTRACT_COLUMNS)].reset_index(drop=True)
    problems: list[str] = []
    for line in frame.to_dict(orient="records"):
        problems += [f"id {show(line['id'])}: {text}" for text in _line_problems(line)]
    duplicates = sorted(frame.loc[frame["id"].duplicated(keep=False), "id"].unique())
    if duplicates:
        problems.append(f"duplicate ids: {duplicates}")
    if problems:
        raise DataError(format_problems(path.name, problems))
    return frame


def attach_abstracts(methods: pd.DataFrame, abstracts: pd.DataFrame) -> pd.DataFrame:
    """A new frame: ``methods`` plus the abstract fields ("" where there is none).

    A line is used only when its id is a method and the title it was fetched for is that
    method's title now. A line that does not fit is left out with a warning, so that
    retitling one paper does not take the page down; but if most lines do not fit, the
    file was written for another version of the methods and is refused.
    """
    titles = methods.set_index("id")["title"]
    fits = [
        titles.get(line_id) == recorded
        for line_id, recorded in zip(
            abstracts["id"], abstracts["method_title"], strict=True
        )
    ]
    stale = abstracts.loc[[not fit for fit in fits], "id"].tolist()
    if stale:
        _handle_stale(stale, len(abstracts))
    usable = abstracts.loc[fits, ["id", *ABSTRACT_FIELDS]]
    joined = methods.merge(usable, on="id", how="left", sort=False)
    return joined.fillna(dict.fromkeys(ABSTRACT_FIELDS, ""))


def _handle_stale(stale: list[str], total: int) -> None:
    sample = stale[:10]
    advice = "Run `python -m tools.fetch_abstracts` to fetch them again."
    if len(stale) > total * MAX_STALE_SHARE:
        raise DataError(
            f"{ABSTRACTS_FILE_NAME} does not fit the methods: {len(stale)} of {total} "
            f"lines are for ids that are missing or whose title changed "
            f"(ids {sample}). "
            f"The methods were probably renumbered or retitled. {advice}"
        )
    _LOG.warning(
        "%s: %d line(s) left out, the id is missing or the title changed (ids %s). %s",
        ABSTRACTS_FILE_NAME,
        len(stale),
        sample,
        advice,
    )


Stamp = tuple[int, int] | None  # modification time (ns) and size, None if no such file
Version = tuple[Stamp, Stamp]


def _stamp(path: Path) -> Stamp:
    try:
        stat = path.stat()
    except OSError:
        return None  # a missing file is reported by the loader, or means "none"
    return (stat.st_mtime_ns, stat.st_size)


def collection_version(methods_path: str | Path) -> Version:
    """Changes whenever either file is replaced, edited, added or removed.

    Time and size of each file, not the newest time of the two: a file put back from an
    older copy has an older time but is still a change.
    """
    return (_stamp(Path(methods_path)), _stamp(abstracts_path_for(methods_path)))


def load_collection(methods_path: str | Path) -> pd.DataFrame:
    """The methods table with its abstracts attached."""
    methods = load_methods(methods_path)
    return attach_abstracts(methods, load_abstracts(abstracts_path_for(methods_path)))
