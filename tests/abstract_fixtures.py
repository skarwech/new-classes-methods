"""Shared fixtures for the abstract fetcher tests: sample answers and a fake web."""

from __future__ import annotations

import json

from tools.abstract_parsing import Abstract

# An "at" sign written as an escape, so that test URLs are not mistaken for e-mail addresses.
AT = "\x40"

LONG = (
    "Traditional classifiers are deployed under a closed-set setting, with both "
    "training and test classes belonging to the same set, but real applications "
    "face inputs of unknown categories."
)

ATOM = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <id>http://arxiv.org/abs/1506.06112v4</id>
  <published>2015-06-19T12:00:00Z</published>
  <title>The Extreme Value
  Machine</title>
  <author><name>Ethan M. Rudd</name></author>
  <author><name>Walter J. Scheirer</name></author>
  <author><name>Terrance E. Boult</name></author>
  <summary>  {LONG}
   With $\\ell_2$ math and a second line.
  </summary>
 </entry>
 <entry>
  <id>http://arxiv.org/abs/1511.06233v2</id>
  <published>2015-11-19T12:00:00Z</published>
  <title>Towards Open Set Deep Networks</title>
  <author><name>Abhijit Bendale</name></author>
  <author><name>Terrance Boult</name></author>
  <summary>{LONG}</summary>
 </entry>
 <entry>
  <id>http://arxiv.org/api/errors#incorrect_id_format_for_abc</id>
  <title>Error</title>
  <summary>incorrect id format for abc</summary>
 </entry>
</feed>"""

CVF_HTML = f"""<html><body>
<div id="papertitle">
Learning Placeholders for Open-Set Recognition
<dd>
<div id="abstract">
{LONG}
</div>
</body></html>"""

PMLR_HTML = f"""<html><body><h1>Streaming Inference for Infinite Non-Stationary Clustering</h1>
<div id="abstract" class="abstract">
{LONG}
</div></body></html>"""


def openalex_work(
    title: str = "Toward Open Set Recognition",
    year: int = 2012,
    *,
    work_id: str | None = None,
    kind: str = "article",
    doi: str = "https://doi.org/10.1109/tpami.2012.256",
    authors: tuple[str, ...] = ("Abhijit Bendale", "Terrance E. Boult"),
) -> str:
    index: dict[str, list[int]] = {}
    for position, word in enumerate(LONG.split()):
        index.setdefault(word, []).append(position)
    work: dict[str, object] = {
        "doi": doi,
        "type": kind,
        "authorships": [{"author": {"display_name": name}} for name in authors],
        "title": title,
        "publication_year": year,
        "abstract_inverted_index": index,
    }
    work["id"] = "https://openalex.org/W2119880843" if work_id is None else work_id
    return json.dumps({key: value for key, value in work.items() if value != ""})


class FakeWeb:
    """Answers a request with the first route whose text occurs in the URL."""

    def __init__(self, *routes: tuple[str, str | None]) -> None:
        self.routes = routes
        self.requested: list[str] = []

    def __call__(self, url: str) -> str | None:
        self.requested.append(url)
        for needle, answer in self.routes:
            if needle in url:
                return answer
        return None


def row(**fields: str) -> dict[str, str]:
    base = {
        "id": "1",
        "method": "M",
        "year": "2016",
        "authors_surnames": "Bendale; Boult",
        "title": "Towards Open Set Deep Networks",
        "arxiv": "",
        "doi": "",
        "paper_url": "",
    }
    return {**base, **fields}


def found(
    title: str,
    *,
    year: int | None = None,
    how: str = "doi",
    method_title: str = "",
    authors: tuple[str, ...] = ("Abhijit Bendale", "Terrance E. Boult"),
    kind: str = "",
    doi: str = "",
) -> Abstract:
    return Abstract(
        text=LONG,
        source="OpenAlex",
        url="https://x.org/1",
        matched_by=how,
        title=title,
        year=year,
        method_title=method_title,
        authors=authors,
        kind=kind,
        doi=doi,
    )
