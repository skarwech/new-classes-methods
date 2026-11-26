"""The abstracts file and the methods file: reading, checking and writing them.

A line of ``abstracts.csv`` is only worth keeping if the site will load it, so the rules
here follow the site's (``explorer/abstracts.py``). A line whose source is ``Manual``
was typed by a person: it is checked and made tidy, but never dropped without a word.

Standard library only.
"""

from __future__ import annotations

import contextlib
import csv
import dataclasses
import logging
import os
import stat
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from .abstract_parsing import (
    MATCHES,
    MAX_ABSTRACT_CHARS,
    SOURCES,
    Abstract,
    has_hidden_character,
    strip_invisible,
    url_problem,
)

_LOG = logging.getLogger("fetch_abstracts")

ABSTRACT_COLUMNS = (
    "id",
    "method_title",
    "source_title",
    "abstract",
    "abstract_source",
    "abstract_url",
    "abstract_match",
)
REQUIRED_METHOD_COLUMNS = (
    "id",
    "title",
    "year",
    "authors_surnames",
    "arxiv",
    "doi",
    "paper_url",
)
MANUAL = "Manual"
DEFAULT_MODE = 0o644


# --- what may be stored ---------------------------------------------------------------


def line_problems(found: Abstract) -> list[str]:
    """What would make the site refuse ``found`` as a line of the abstracts file."""
    problems: list[str] = []
    if not found.text.strip():
        problems.append("abstract is empty")
    if len(found.text) > MAX_ABSTRACT_CHARS:
        problems.append(f"abstract is over {MAX_ABSTRACT_CHARS} characters")
    if has_hidden_character(found.text):
        problems.append("abstract has a line break or a control or invisible character")
    if has_hidden_character(found.title):
        problems.append("the source's title has a character the file cannot hold")
    if found.source not in SOURCES:
        problems.append(
            f"abstract_source {found.source!r} is not one of {list(SOURCES)}"
        )
    if found.matched_by not in MATCHES:
        problems.append(
            f"abstract_match {found.matched_by!r} is not one of {list(MATCHES)}"
        )
    problem = url_problem(found.source, found.url)
    if problem:
        problems.append(f"abstract_url {problem}")
    elif has_hidden_character(found.url):
        problems.append("abstract_url has a control or invisible character")
    return problems


def storable(found: Abstract) -> bool:
    """May a find of this run be stored? The site accepts it; the link is https."""
    return not line_problems(found) and found.url.startswith("https://")


# --- lines typed by a person ----------------------------------------------------------


def _tidy(text: str) -> str:
    """One line of text: pasted line breaks and runs of spaces become single spaces."""
    return " ".join(strip_invisible(text).split())


def _manual_problems(titles: Mapping[str, str], key: str, line: Abstract) -> list[str]:
    if key not in titles:
        return [f"id {key}: no such method in the methods file"]
    problems = [f"id {key}: {text}" for text in line_problems(line)]
    if titles[key] != line.method_title:
        problems.append(
            f"id {key}: written for another title ({line.method_title!r}). If it is "
            f"still the same paper, set method_title to {titles[key]!r}; "
            "if not, remove the line"
        )
    return problems


def prepare_manual(
    rows: Sequence[Mapping[str, str]], existing: Mapping[str, Abstract]
) -> tuple[dict[str, Abstract], list[str]]:
    """The lines, with typed ones made tidy, and what is wrong with the typed ones.

    The caller stops on a problem instead of going on: dropping a typed line, or writing
    a file the site refuses, would be worse than not running.
    """
    titles = {row["id"]: row["title"] for row in rows}
    prepared: dict[str, Abstract] = {}
    problems: list[str] = []
    for key, line in existing.items():
        if line.source == MANUAL:
            line = dataclasses.replace(line, text=_tidy(line.text))
            problems += _manual_problems(titles, key, line)
        prepared[key] = line
    return prepared, problems


def usable_existing(
    rows: Sequence[Mapping[str, str]], existing: Mapping[str, Abstract]
) -> dict[str, Abstract]:
    """Lines that still belong to their method and may stay in the file.

    A line stored for another title belongs to another paper (the ids were renumbered).
    An automatic line the site would refuse is dropped, to be fetched again.
    """
    titles = {row["id"]: row["title"] for row in rows}
    return {
        key: line
        for key, line in existing.items()
        if titles.get(key) == line.method_title
        and (line.source == MANUAL or storable(line))
    }


def with_manual_edits(
    path: Path, rows: Sequence[Mapping[str, str]], results: Mapping[str, Abstract]
) -> dict[str, Abstract]:
    """``results`` plus the typed lines in the file now.

    A run takes a long time, and a person may add or correct a line meanwhile. Reading
    the file again just before writing keeps that work. Raises if it cannot be read.
    """
    merged = dict(results)
    if not path.exists():
        return merged
    titles = {row["id"]: row["title"] for row in rows}
    prepared, _ = prepare_manual(rows, read_abstracts(path))
    for key, line in prepared.items():
        if line.source != MANUAL:
            continue
        problems = _manual_problems(titles, key, line)
        if problems:
            _LOG.warning(
                "a typed line added during the run was not kept: %s", problems[0]
            )
        else:
            merged[key] = line
    return merged


# --- reading and writing --------------------------------------------------------------


def _read_rows(path: Path, required: Sequence[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, restval="")  # a short row has empty cells
        missing = [name for name in required if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name} is missing columns: {missing}")
        return list(reader)


def read_abstracts(path: Path) -> dict[str, Abstract]:
    """Read what ``write_abstracts`` wrote; ``source_title`` may be absent."""
    required = [name for name in ABSTRACT_COLUMNS if name != "source_title"]
    return {
        row["id"]: Abstract(
            text=row["abstract"],
            source=row["abstract_source"],
            url=row["abstract_url"],
            matched_by=row["abstract_match"],
            title=row.get("source_title") or "",
            method_title=row["method_title"],
        )
        for row in _read_rows(path, required)
    }


def read_methods(path: Path) -> list[dict[str, str]]:
    rows = _read_rows(path, REQUIRED_METHOD_COLUMNS)
    ids = [row["id"] for row in rows]
    if "" in ids or len(set(ids)) != len(ids):
        raise ValueError(f"{path.name} has an empty or repeated id")
    return rows


def write_abstracts(
    path: Path, rows: Sequence[Mapping[str, str]], results: Mapping[str, Abstract]
) -> None:
    """Write the abstracts in the order of ``rows``: UTF-8 CSV with a byte-order mark.

    Each line also records the title of the method it was fetched for, so that a later
    renumbering of the methods cannot attach an abstract to the wrong paper unnoticed.
    The file is replaced only once it is complete and on disk: a failure leaves the old
    one alone. It keeps the old file's permissions (a new one is world-readable, as a
    data file of a site should be, not the 0600 of a temporary file).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else DEFAULT_MODE
    handle, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=".abstracts-", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", newline="", encoding="utf-8-sig") as out:
            writer = csv.writer(out, lineterminator="\n")
            writer.writerow(ABSTRACT_COLUMNS)
            for row in rows:
                found = results.get(row["id"])
                if found:
                    writer.writerow(
                        [
                            row["id"],
                            row["title"],
                            found.title,
                            found.text,
                            found.source,
                            found.url,
                            found.matched_by,
                        ]
                    )
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise
