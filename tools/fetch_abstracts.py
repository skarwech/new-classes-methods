#!/usr/bin/env python3
"""Fetch the abstract of each method in data/methods_public.csv.

The abstracts are written to data/abstracts.csv. Standard library only; no key, no
account. Run it from the site folder:

    python -m tools.fetch_abstracts            # only methods that have no abstract yet
    python -m tools.fetch_abstracts --refresh  # look for newer text for every method

Sources, tried in this order for each method (the first that passes the title check
wins):

1. arXiv, by arXiv id (from the ``arxiv`` column or an arxiv.org link), in batches.
2. OpenAlex, then Crossref, by DOI (from the ``doi`` column or a doi.org link).
3. The paper page itself when it is on openaccess.thecvf.com or proceedings.mlr.press.
4. A strict title search on OpenAlex, then on arXiv. Only an almost identical title from
   about the same year is accepted.

Every abstract is checked against the title in the CSV, so a wrong identifier or a
wrong search hit is rejected, never stored. A search hit must also be a paper (not a
dataset or a review of it) with no other DOI, written by someone the methods file
names. The file records where each abstract came from and how it was matched, and what
the source calls the paper (``source_title``).

A line whose ``abstract_source`` is ``Manual`` was typed by a person: it is never
fetched again or replaced, not even with ``--refresh``, and it is kept if the file is
edited while the tool runs. If a typed line does not fit the methods (the title was
corrected, the id is gone) or the site would refuse it, the tool stops before fetching
anything and says which line and why. With ``--refresh`` an automatic abstract is
replaced only by a find that is at least as well matched, so a failed refresh loses
nothing. The file is saved every few methods, so an interrupt loses little.

OpenReview, ScienceDirect and IEEE refuse automated clients and are not used. No contact
details are sent: the requests carry a generic User-Agent only.

Exit status: 0 on success, even if some methods have no abstract; 1 if a source failed
along the way (the file is still written); 2 if a file could not be read or written, or
a typed line needs attention; 130 if interrupted.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import functools
import json
import logging
import re
import sys
import urllib.parse
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from .abstract_file import (
    MANUAL,
    prepare_manual,
    read_abstracts,
    read_methods,
    storable,
    usable_existing,
    with_manual_edits,
    write_abstracts,
)
from .abstract_parsing import (
    Abstract,
    accept,
    arxiv_id_of,
    doi_of,
    normalize_title,
    openalex_item,
    parse_arxiv_atom,
    parse_crossref_work,
    parse_cvf,
    parse_openalex_work,
    parse_pmlr,
)
from .abstract_web import HostNotAllowed, Web

_LOG = logging.getLogger("fetch_abstracts")

SITE_ROOT = Path(__file__).resolve().parent.parent
ARXIV_BATCH = 40
CHECKPOINT_EVERY = 20  # methods between saves of the file
OPENALEX_FIELDS = (
    "id,doi,title,publication_year,abstract_inverted_index,authorships,type"
)
# How well a find is matched; a refresh only replaces a line with a find as strong.
STRENGTH = {"manual": 4, "arxiv id": 3, "doi": 3, "paper url": 2, "title": 1}

Fetch = Callable[[str], "str | None"]


# --- failures -------------------------------------------------------------------------


def _guarded(
    call: Callable[[], Any], default: Any, what: str, problems: list[str]
) -> Any:
    """``call()``, or ``default`` if it fails; the failure is logged and recorded.

    A network error or an odd answer from a third party costs one source for one
    method, not the run.
    """
    try:
        return call()
    except (OSError, HostNotAllowed) as error:
        _LOG.warning("  %s failed: %s", what, error)
        problems.append(f"{what}: {error}")
    except Exception as error:  # third-party data of any shape
        _LOG.exception("  %s: unexpected %s", what, type(error).__name__)
        problems.append(f"{what}: unexpected {type(error).__name__}")
    return default


# --- the sources ----------------------------------------------------------------------


def _quote(text: str) -> str:
    return urllib.parse.quote(text, safe="/:()")


def _arxiv_batch(fetch: Fetch, batch: Sequence[str]) -> dict[str, Abstract]:
    url = (
        "https://export.arxiv.org/api/query?"
        f"id_list={','.join(batch)}&max_results={len(batch)}"
    )
    return parse_arxiv_atom(fetch(url) or "")


def fetch_arxiv_ids(
    fetch: Fetch, ids: Sequence[str], problems: list[str]
) -> dict[str, Abstract]:
    """Abstracts for arXiv ids, a batch per request; a failed batch loses only that."""
    found: dict[str, Abstract] = {}
    for start in range(0, len(ids), ARXIV_BATCH):
        batch = ids[start : start + ARXIV_BATCH]
        got = _guarded(
            functools.partial(_arxiv_batch, fetch, batch),
            {},
            f"arXiv batch of {len(batch)}",
            problems,
        )
        if len(got) < len(batch):
            _LOG.warning(
                "  arXiv returned %d of %d abstracts asked for", len(got), len(batch)
            )
        found |= got
    return found


def doi_candidates(
    fetch: Fetch, doi: str, problems: list[str]
) -> Iterator[Abstract | None]:
    """OpenAlex's abstract for a DOI, then (only if asked for more) Crossref's."""
    yield _guarded(
        lambda: parse_openalex_work(
            fetch(
                f"https://api.openalex.org/works/doi:{_quote(doi)}?select={OPENALEX_FIELDS}"
            )
            or "",
            matched_by="doi",
        ),
        None,
        f"OpenAlex {doi}",
        problems,
    )
    yield _guarded(
        lambda: parse_crossref_work(
            fetch(f"https://api.crossref.org/works/{_quote(doi)}") or "", doi
        ),
        None,
        f"Crossref {doi}",
        problems,
    )


def fetch_paper_page(fetch: Fetch, url: str) -> Abstract | None:
    url = re.sub(r"^http://", "https://", url)  # the known hosts all serve https
    parts = urllib.parse.urlsplit(url)
    if parts.hostname == "openaccess.thecvf.com":
        page_url = re.sub(r"/papers/(.+)\.pdf$", r"/html/\1.html", url)
        return parse_cvf(fetch(page_url) or "", page_url)
    if parts.hostname == "proceedings.mlr.press" and url.endswith(".html"):
        return parse_pmlr(fetch(url) or "", url)
    return None  # any other site is not contacted


def search_openalex(fetch: Fetch, title: str) -> list[Abstract]:
    words = " ".join(normalize_title(title).split()[:12])
    url = (
        "https://api.openalex.org/works?"
        f"filter=title.search:{urllib.parse.quote(words)}&per-page=5&select={OPENALEX_FIELDS}"
    )
    try:
        payload = json.loads(fetch(url) or "")
    except ValueError:
        return []
    results = payload.get("results") if isinstance(payload, dict) else None
    items = (
        openalex_item(work, matched_by="title")
        for work in results or []
        if isinstance(work, dict)
    )
    return [item for item in items if item]


def search_arxiv(fetch: Fetch, title: str) -> list[Abstract]:
    query = urllib.parse.quote(f'ti:"{normalize_title(title)}"')
    feed = fetch(
        f"https://export.arxiv.org/api/query?search_query={query}&max_results=3"
    )
    return [
        dataclasses.replace(item, matched_by="title")
        for item in parse_arxiv_atom(feed or "").values()
    ]


# --- one method -----------------------------------------------------------------------


def _first_accepted(
    row: Mapping[str, str], candidates: Iterable[Abstract | None]
) -> Abstract | None:
    """The first candidate that belongs to ``row``; later ones are not even produced."""
    for candidate in candidates:
        if candidate is not None and accept(row, candidate):
            return candidate
    return None


def _from_identifiers(
    fetch: Fetch, row: Mapping[str, str], problems: list[str]
) -> Abstract | None:
    doi, url = doi_of(row), row.get("paper_url", "")
    if doi:
        found = _first_accepted(row, doi_candidates(fetch, doi, problems))
        if found:
            return found
    if url:
        page = _guarded(
            lambda: fetch_paper_page(fetch, url), None, f"page {url[:60]}", problems
        )
        return _first_accepted(row, [page])
    return None


def _from_title_search(
    fetch: Fetch, row: Mapping[str, str], problems: list[str]
) -> Abstract | None:
    title = row["title"]
    for name, search in (("OpenAlex", search_openalex), ("arXiv", search_arxiv)):
        hits = _guarded(
            functools.partial(search, fetch, title),
            [],
            f"{name} search for {title[:40]!r}",
            problems,
        )
        found = _first_accepted(row, hits)
        if found:
            return found
    return None


def _find_without_arxiv(
    fetch: Fetch, row: Mapping[str, str], problems: list[str]
) -> Abstract | None:
    return _from_identifiers(fetch, row, problems) or _from_title_search(
        fetch, row, problems
    )


# --- all methods ----------------------------------------------------------------------


def collect(
    rows: Sequence[Mapping[str, str]],
    fetch: Fetch,
    *,
    existing: Mapping[str, Abstract] | None = None,
    refresh: bool = False,
    problems: list[str] | None = None,
    checkpoint: Callable[[Mapping[str, Abstract]], None] | None = None,
    checkpoint_every: int | None = None,
) -> tuple[dict[str, Abstract], list[str]]:
    """Abstracts by method id, and the ids nothing was found for.

    ``checkpoint`` is called with all the lines so far, kept ones included, after every
    ``checkpoint_every`` (default ``CHECKPOINT_EVERY``) methods, to save them.
    """
    log = problems if problems is not None else []
    every = checkpoint_every or CHECKPOINT_EVERY
    results = usable_existing(rows, existing or {})
    todo = [
        row
        for row in rows
        if row["id"] not in results or (refresh and results[row["id"]].source != MANUAL)
    ]
    wanted = sorted({arxiv_id_of(row) for row in todo} - {""})
    by_arxiv = fetch_arxiv_ids(fetch, wanted, log) if wanted else {}
    for index, row in enumerate(todo, start=1):
        found = _find_one(fetch, row, by_arxiv, log)
        if found and _no_weaker(found, results.get(row["id"])):
            results[row["id"]] = dataclasses.replace(found, method_title=row["title"])
        if checkpoint is not None and index % every == 0:
            checkpoint(dict(results))
    misses = [row["id"] for row in rows if row["id"] not in results]
    return results, misses


def _no_weaker(found: Abstract, old: Abstract | None) -> bool:
    """May ``found`` take the place of ``old``? Not if it is matched less strongly."""
    return old is None or STRENGTH.get(found.matched_by, 0) >= STRENGTH.get(
        old.matched_by, 0
    )


def _find_one(
    fetch: Fetch,
    row: Mapping[str, str],
    by_arxiv: Mapping[str, Abstract],
    problems: list[str],
) -> Abstract | None:
    found = _first_accepted(row, [by_arxiv.get(arxiv_id_of(row))])
    found = found or _guarded(
        lambda: _find_without_arxiv(fetch, row, problems),
        None,
        f"method {row['id']}",
        problems,
    )
    return found if found is not None and storable(found) else None


# --- the command ----------------------------------------------------------------------


def _report(
    rows: Sequence[Mapping[str, str]],
    results: Mapping[str, Abstract],
    misses: Sequence[str],
    problems: Sequence[str],
) -> None:
    by_source: dict[str, int] = {}
    for found in results.values():
        by_source[found.source] = by_source.get(found.source, 0) + 1
    _LOG.info("abstracts: %d of %d methods  %s", len(results), len(rows), by_source)
    if misses:
        _LOG.info("none found: %s", ", ".join(misses))
    if problems:
        _LOG.warning(
            "%d source call(s) failed; run again later to fill gaps", len(problems)
        )


class _Saver:
    """Saves the results, keeping what a person typed into the file meanwhile.

    If the file cannot be updated (damaged, not writable), the results go to a side
    file next to it, and ``failed`` is set.
    """

    def __init__(self, path: Path, rows: Sequence[Mapping[str, str]]) -> None:
        self.path, self.rows, self.failed = path, rows, False

    def __call__(self, results: Mapping[str, Abstract]) -> None:
        try:
            merged = with_manual_edits(self.path, self.rows, results)
            write_abstracts(self.path, self.rows, merged)
        except (OSError, ValueError, csv.Error) as error:
            self.failed = True
            _LOG.error("%s could not be written: %s", self.path.name, error)
            self._save_aside(results)

    def _save_aside(self, results: Mapping[str, Abstract]) -> None:
        side = self.path.with_name(self.path.name + ".new")
        try:
            write_abstracts(side, self.rows, results)
        except OSError as error:
            _LOG.error("%s could not be written either: %s", side.name, error)
        else:
            _LOG.error("the abstracts are in %s instead", side.name)


def _read_inputs(
    methods: Path, out: Path
) -> tuple[list[dict[str, str]], dict[str, Abstract]] | None:
    """The methods and the existing lines, or None after saying what is wrong."""
    try:
        rows = read_methods(methods)
        existing, problems = prepare_manual(
            rows, read_abstracts(out) if out.exists() else {}
        )
    except (OSError, ValueError, csv.Error) as error:
        _LOG.error("cannot read a file: %s", error)
        return None
    for text in problems:
        _LOG.error("%s: %s", out.name, text)
    if problems:
        _LOG.error(
            "nothing was fetched or changed; fix the line(s) above and run again"
        )
        return None
    return rows, existing


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch abstracts for the methods.")
    parser.add_argument(
        "--methods", type=Path, default=SITE_ROOT / "data" / "methods_public.csv"
    )
    parser.add_argument(
        "--out", type=Path, default=SITE_ROOT / "data" / "abstracts.csv"
    )
    parser.add_argument(
        "--refresh", action="store_true", help="look for newer text for every method"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    inputs = _read_inputs(args.methods, args.out)
    if inputs is None:
        return 2
    rows, existing = inputs
    save, problems = _Saver(args.out, rows), []
    try:
        results, misses = collect(
            rows,
            Web(),
            existing=existing,
            refresh=args.refresh,
            problems=problems,
            checkpoint=save,
        )
    except KeyboardInterrupt:
        _LOG.warning("interrupted; the abstracts found so far were saved")
        return 130
    save(results)
    _report(rows, results, misses, problems)
    return 2 if save.failed else (1 if problems else 0)


if __name__ == "__main__":
    sys.exit(main())
