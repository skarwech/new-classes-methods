"""The abstract fetcher: the order of sources, failures, refresh rules, the file, the CLI.

No test touches the network: sources are answered by a small fake web.
"""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

import pytest

import tools.fetch_abstracts as fetcher
from explorer.abstracts import ABSTRACT_COLUMNS as SITE_COLUMNS
from explorer.abstracts import load_abstracts
from explorer.constants import ABSTRACT_MATCHES, ABSTRACT_SOURCES, MAX_ABSTRACT_CHARS
from tests.abstract_fixtures import (
    AT,
    ATOM,
    CVF_HTML,
    LONG,
    PMLR_HTML,
    FakeWeb,
    openalex_work,
    row,
)
from tools import abstract_parsing
from tools.abstract_file import (
    ABSTRACT_COLUMNS,
    line_problems,
    prepare_manual,
    read_abstracts,
    read_methods,
    storable,
    write_abstracts,
)
from tools.abstract_parsing import Abstract
from tools.fetch_abstracts import collect, doi_candidates, fetch_arxiv_ids

pytestmark = pytest.mark.unit

TITLE = "Towards Open Set Deep Networks"


def stored(text: str = LONG, **fields: str) -> Abstract:
    base = {
        "source": "arXiv",
        "url": "https://arxiv.org/abs/1511.06233",
        "matched_by": "arxiv id",
        "title": "source title",
        "method_title": TITLE,
    }
    return Abstract(text=text, **{**base, **fields})  # type: ignore[arg-type]


def atom_for(url: str, titles: dict[str, str] | None = None) -> str:
    """An arXiv answer with an entry for every id asked for in ``url``."""
    ids = re.search(r"id_list=([^&]+)", url)
    wanted = ids.group(1).split(",") if ids else []
    entries = "".join(
        f"<entry><id>http://arxiv.org/abs/{i}v1</id><published>2016-01-01</published>"
        f"<title>{(titles or {}).get(i, TITLE)}</title><summary>{LONG}</summary></entry>"
        for i in wanted
    )
    return f"<feed>{entries}</feed>"


# --- arXiv ----------------------------------------------------------------------------


def test_arxiv_ids_are_fetched_in_batches_and_matched_by_id() -> None:
    rows = [
        row(id="4", arxiv="1511.06233", title="Towards Open Set Deep Networks"),
        row(id="5", arxiv="1506.06112", title="The Extreme Value Machine"),
    ]
    web = FakeWeb(("export.arxiv.org", ATOM))
    results, misses = collect(rows, web)
    assert set(results) == {"4", "5"}
    assert results["4"].source == "arXiv"
    assert results["4"].matched_by == "arxiv id"
    assert results["4"].method_title == "Towards Open Set Deep Networks"
    assert (
        results["4"].title == "Towards Open Set Deep Networks"
    )  # the source's own title
    assert misses == []
    assert len([u for u in web.requested if "export.arxiv.org" in u]) == 1


def test_many_ids_are_split_into_batches_of_forty() -> None:
    ids = [f"2001.{n:05d}" for n in range(85)]
    web = FakeWeb()
    fetch_arxiv_ids(web, ids, [])
    assert len(web.requested) == 3
    assert web.requested[0].count(",") == 39
    assert web.requested[2].count(",") == 4


def test_a_failing_batch_does_not_lose_the_other_batches() -> None:
    ids = [f"2001.{n:05d}" for n in range(85)]

    def fetch(url: str) -> str | None:
        if ids[40] in url:  # the second batch
            raise OSError("timed out")
        return atom_for(url)

    problems: list[str] = []
    got = fetch_arxiv_ids(fetch, ids, problems)
    assert set(got) == set(ids[:40]) | set(ids[80:])
    assert len(problems) == 1
    assert "arXiv batch" in problems[0]


def test_a_batch_that_returns_fewer_entries_than_asked_is_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="fetch_abstracts")
    fetch_arxiv_ids(
        lambda url: atom_for("id_list=2001.00001"), ["2001.00001", "2001.00002"], []
    )
    assert "returned 1 of 2" in caplog.text


def test_an_arxiv_hit_with_the_wrong_title_is_rejected_not_stored() -> None:
    rows = [
        row(id="4", arxiv="1511.06233", title="Something Else Entirely About Graphs")
    ]
    results, misses = collect(rows, FakeWeb(("export.arxiv.org", ATOM)))
    assert results == {}
    assert misses == ["4"]


# --- DOI, pages, title search ------------------------------------------------------------


def test_crossref_is_only_asked_when_openalex_gave_nothing_acceptable() -> None:
    rows = [
        row(id="1", doi="10.1109/TPAMI.2012.256", title="Toward Open Set Recognition")
    ]
    web = FakeWeb(("api.openalex.org/works/doi:10.1109", openalex_work()))
    results, _ = collect(rows, web)
    assert results["1"].source == "OpenAlex"
    assert not [u for u in web.requested if "crossref" in u]


def test_a_doi_goes_to_crossref_when_openalex_has_no_abstract_or_fails() -> None:
    crossref = json.dumps(
        {
            "message": {
                "title": ["Toward Open Set Recognition"],
                "abstract": f"<jats:p>{LONG}</jats:p>",
            }
        }
    )
    rows = [
        row(id="2", doi="10.1/other", title="Toward Open Set Recognition"),
        row(id="3", doi="10.1/broken", title="Toward Open Set Recognition"),
    ]

    def fetch(url: str) -> str | None:
        if "openalex.org/works/doi:10.1/broken" in url:
            raise OSError("bad request")
        if "api.crossref.org" in url:
            return crossref
        return None

    problems: list[str] = []
    results, misses = collect(rows, fetch, problems=problems)
    assert results["2"].source == "Crossref"
    assert results["2"].matched_by == "doi"
    assert results["3"].source == "Crossref"  # a failing OpenAlex did not stop Crossref
    assert misses == []
    assert len(problems) == 1
    assert "OpenAlex" in problems[0]


def test_doi_candidates_are_lazy() -> None:
    web = FakeWeb(("openalex", openalex_work()))
    candidates = doi_candidates(web, "10.1/x", [])
    next(candidates)
    assert not [u for u in web.requested if "crossref" in u]


def test_cvf_and_pmlr_pages_are_read_when_there_is_no_id() -> None:
    rows = [
        row(
            id="11",
            title="Learning Placeholders for Open-Set Recognition",
            paper_url="https://openaccess.thecvf.com/content/CVPR2021/papers/Zhou_x_paper.pdf",
        ),
        row(
            id="12",
            title="Streaming Inference for Infinite Non-Stationary Clustering",
            paper_url="https://proceedings.mlr.press/v199/schaeffer22a.html",
        ),
    ]
    web = FakeWeb(
        ("openaccess.thecvf.com/content/CVPR2021/html/Zhou_x_paper.html", CVF_HTML),
        ("proceedings.mlr.press", PMLR_HTML),
    )
    results, _ = collect(rows, web)
    assert results["11"].source == "CVF"
    assert results["12"].source == "PMLR"


def test_a_plain_http_link_to_a_known_host_is_read_over_https() -> None:
    rows = [
        row(
            id="101",
            title="Learning Placeholders for Open-Set Recognition",
            paper_url="http://openaccess.thecvf.com/content_CVPR_2019/papers/Hou_x_paper.pdf",
        )
    ]
    web = FakeWeb(
        (
            "https://openaccess.thecvf.com/content_CVPR_2019/html/Hou_x_paper.html",
            CVF_HTML,
        )
    )
    results, _ = collect(rows, web)
    assert results["101"].source == "CVF"
    assert results["101"].url.startswith("https://")


def test_a_paper_link_on_another_site_is_never_fetched() -> None:
    rows = [row(id="9", title="Anything", paper_url="https://www.sciencedirect.com/x")]
    web = FakeWeb()
    collect(rows, web)
    assert not [u for u in web.requested if "sciencedirect" in u]


def test_a_page_that_belongs_to_another_paper_is_rejected() -> None:
    rows = [
        row(
            id="11",
            title="A Completely Different Paper About Something Else",
            paper_url="https://proceedings.mlr.press/v199/schaeffer22a.html",
        )
    ]
    results, misses = collect(rows, FakeWeb(("proceedings.mlr.press", PMLR_HTML)))
    assert results == {}
    assert misses == ["11"]


def test_a_title_search_is_the_last_resort_and_needs_a_close_match() -> None:
    hits = [
        json.loads(openalex_work(title="Unrelated Paper", year=2016)),
        json.loads(openalex_work(title=TITLE, year=2016)),
    ]
    rows = [row(id="9", title=TITLE, year="2016")]
    results, misses = collect(
        rows, FakeWeb(("api.openalex.org/works?", json.dumps({"results": hits})))
    )
    assert results["9"].matched_by == "title"
    assert misses == []
    only_wrong = json.dumps({"results": hits[:1]})
    results, misses = collect(rows, FakeWeb(("api.openalex.org/works?", only_wrong)))
    assert results == {}
    assert misses == ["9"]


def test_an_arxiv_title_search_hit_needs_the_year_from_the_feed() -> None:
    rows = [row(id="9", title="The Extreme Value Machine", year="2018")]
    results, misses = collect(rows, FakeWeb(("search_query", ATOM)))  # published 2015
    assert results["9"].source == "arXiv"
    assert results["9"].matched_by == "title"
    far = [row(id="9", title="The Extreme Value Machine", year="2024")]
    assert collect(far, FakeWeb(("search_query", ATOM)))[1] == ["9"]


def test_one_failing_source_does_not_stop_the_run() -> None:
    def broken(url: str) -> str | None:
        if "openalex" in url:
            raise OSError("network down")
        return ATOM if "arxiv" in url else None

    problems: list[str] = []
    rows = [
        row(id="4", arxiv="1511.06233"),
        row(id="7", doi="10.1/x", title="Whatever"),
    ]
    results, misses = collect(rows, broken, problems=problems)
    assert set(results) == {"4"}
    assert misses == ["7"]
    assert problems


def test_an_unexpected_error_costs_one_source_of_one_method_and_is_recorded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fetch(url: str) -> str | None:
        if "api.crossref.org" in url:
            raise TypeError("a shape nobody planned for")
        return ATOM if "arxiv" in url else None

    problems: list[str] = []
    rows = [
        row(id="7", doi="10.1/x", title="Whatever"),
        row(id="4", arxiv="1511.06233"),
    ]
    results, misses = collect(rows, fetch, problems=problems)
    assert set(results) == {"4"}
    assert misses == ["7"]
    assert any("Crossref" in p and "TypeError" in p for p in problems)
    assert "Traceback" in caplog.text  # the cause is in the log, not swallowed


# --- what may be written ------------------------------------------------------------------


def test_storable_enforces_what_the_site_will_accept() -> None:
    assert storable(stored())
    assert not storable(stored(url=""))
    assert not storable(stored(url="http://arxiv.org/abs/1"))
    assert not storable(stored(source="Wikipedia"))
    assert not storable(stored(text="x" * (MAX_ABSTRACT_CHARS + 1)))
    assert not storable(stored(text="has a ​ hidden character " * 5))
    assert not storable(stored(text=""))


def test_an_existing_automatic_line_the_site_would_refuse_is_fetched_again() -> None:
    bad = stored(source="Wikipedia")
    rows = [row(id="1", arxiv="1511.06233", title=TITLE)]
    results, _ = collect(rows, FakeWeb(("export.arxiv.org", ATOM)), existing={"1": bad})
    assert results["1"].source == "arXiv"
    assert collect(rows, FakeWeb(), existing={"1": bad})[1] == [
        "1"
    ]  # and not kept as it was


def test_a_manual_line_with_line_breaks_is_made_one_line_not_refused() -> None:
    manual = stored(
        "Two\nlines typed by hand,\n\n with a blank line. " * 5,
        source="Manual",
        url="http://example.org/p",
        matched_by="manual",
    )
    lines, problems = prepare_manual([row(id="1", title=TITLE)], {"1": manual})
    assert problems == []
    assert (
        lines["1"].text == ("Two lines typed by hand, with a blank line. " * 5).strip()
    )
    assert "\n" not in lines["1"].text
    assert lines["1"].text.startswith("Two lines typed by hand, with a blank line.")
    assert manual.text.count("\n") > 0  # the input was not changed


def test_a_manual_line_that_does_not_fit_the_methods_is_a_problem_not_a_silent_loss() -> (
    None
):
    manual = stored(
        "By hand. " * 20, source="Manual", url="https://e.org/p", matched_by="manual"
    )
    rows = [row(id="1", title="The Title Was Corrected"), row(id="2", title=TITLE)]
    lines, problems = prepare_manual(rows, {"1": manual, "3": manual})
    assert any("id 1" in p and "another title" in p for p in problems)
    assert any("id 3" in p and "no such method" in p for p in problems)


def test_a_manual_line_the_site_would_refuse_is_a_problem() -> None:
    bad = stored(
        "By hand. " * 20, source="Manual", url="not a link", matched_by="manual"
    )
    _, problems = prepare_manual([row(id="1", title=TITLE)], {"1": bad})
    assert any("id 1" in p and "abstract_url" in p for p in problems)
    odd_source = stored("By hand. " * 20, source="Manual", matched_by="whatever")
    assert prepare_manual([row(id="1", title=TITLE)], {"1": odd_source})[1]


def test_lines_that_are_not_manual_are_left_alone_by_the_manual_check() -> None:
    auto = stored()
    lines, problems = prepare_manual([row(id="1", title=TITLE)], {"1": auto})
    assert problems == []
    assert lines == {"1": auto}


def test_a_lone_surrogate_anywhere_makes_a_line_unstorable() -> None:
    assert not storable(stored(title="Bad \ud835 title"))
    assert not storable(stored(text="x" * 200 + "\ud835"))
    assert not storable(stored(url="https://arxiv.org/abs/1\ud835"))
    assert not storable(stored(url="https://arxiv.org/abs/1\u200b"))
    assert any(
        "invisible" in p
        for p in line_problems(stored(url="https://arxiv.org/abs/1\u200b"))
    )
    assert line_problems(stored(url="https://example.org/a b"))  # a space in a link


def test_a_manual_line_may_use_an_http_link_but_a_find_must_use_https() -> None:
    plain = stored(url="http://example.org/p", source="Manual", matched_by="manual")
    assert line_problems(plain) == []
    assert not storable(plain)


def test_a_find_the_site_would_refuse_is_not_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    plain = parse_atom_for_test()
    odd = {
        key: replace(value, url="http://arxiv.org/abs/" + key)
        for key, value in plain.items()
    }
    monkeypatch.setattr(fetcher, "parse_arxiv_atom", lambda feed: odd)
    results, misses = collect(
        [row(id="4", arxiv="1511.06233")], FakeWeb(("arxiv", ATOM))
    )
    assert results == {}
    assert misses == ["4"]


def parse_atom_for_test() -> dict[str, Abstract]:
    from tools.abstract_parsing import parse_arxiv_atom

    return parse_arxiv_atom(ATOM)


# --- existing lines and --refresh -----------------------------------------------------------


def test_rows_that_already_have_an_abstract_are_not_fetched_again() -> None:
    web = FakeWeb(("export.arxiv.org", ATOM))
    results, _ = collect(
        [row(id="4", arxiv="1511.06233", title=TITLE)], web, existing={"4": stored()}
    )
    assert results == {"4": stored()}
    assert web.requested == []


def test_an_abstract_stored_for_a_different_title_is_fetched_again() -> None:
    """If ids are renumbered, an id's old abstract belongs to another paper."""
    stale = {"4": stored("Old text. " * 20, method_title="Some Other Paper Entirely")}
    rows = [row(id="4", arxiv="1511.06233", title=TITLE)]
    results, _ = collect(rows, FakeWeb(("export.arxiv.org", ATOM)), existing=stale)
    assert results["4"].text == LONG
    assert results["4"].method_title == TITLE


def test_refresh_replaces_an_abstract_only_when_a_new_one_is_found() -> None:
    old = stored("Old abstract text. " * 10)
    rows = [row(id="4", arxiv="1511.06233", title=TITLE)]
    nothing, misses = collect(rows, FakeWeb(), existing={"4": old}, refresh=True)
    assert nothing == {"4": old}
    assert misses == []
    renewed, _ = collect(
        rows, FakeWeb(("export.arxiv.org", ATOM)), existing={"4": old}, refresh=True
    )
    assert renewed["4"].text == LONG


def test_a_refresh_never_swaps_a_strong_match_for_a_weaker_one() -> None:
    """If arXiv returns nothing this time, a title hit must not replace the id match."""
    old = stored("Old text by id. " * 12, matched_by="arxiv id")
    hits = json.dumps({"results": [json.loads(openalex_work(title=TITLE, year=2016))]})
    rows = [row(id="4", arxiv="1511.06233", title=TITLE)]
    web = FakeWeb(("api.openalex.org/works?", hits))  # arXiv: nothing
    results, _ = collect(rows, web, existing={"4": old}, refresh=True)
    assert results["4"] == old
    assert [u for u in web.requested if "api.openalex.org/works?" in u]  # it did look


def test_a_refresh_may_replace_a_match_with_an_equal_or_stronger_one() -> None:
    old = stored(
        "Old text by title. " * 12,
        source="OpenAlex",
        matched_by="title",
        url="https://openalex.org/W1",
    )
    rows = [row(id="4", arxiv="1511.06233", title=TITLE)]
    results, _ = collect(
        rows, FakeWeb(("export.arxiv.org", ATOM)), existing={"4": old}, refresh=True
    )
    assert results["4"].matched_by == "arxiv id"
    assert results["4"].text == LONG


def test_the_results_are_handed_over_every_so_many_methods_with_nothing_lost() -> None:
    """A checkpoint during a refresh still holds the lines not looked at yet."""
    rows = [row(id=str(i), arxiv="", title=f"Paper number {i}") for i in range(1, 6)]
    existing = {
        str(i): stored(f"Old {i}. " * 40, method_title=f"Paper number {i}")
        for i in range(1, 6)
    }
    seen: list[set[str]] = []
    collect(
        rows,
        FakeWeb(),
        existing=existing,
        refresh=True,
        checkpoint=lambda partial: seen.append(set(partial)),
        checkpoint_every=2,
    )
    assert len(seen) == 2  # after the 2nd and the 4th method
    assert all(ids == {"1", "2", "3", "4", "5"} for ids in seen)


def test_a_manual_line_is_never_replaced_or_fetched_even_when_refreshing() -> None:
    manual = stored(
        "Typed in by hand. " * 10,
        source="Manual",
        url="https://example.org/p",
        matched_by="manual",
    )
    web = FakeWeb(("export.arxiv.org", ATOM))
    results, _ = collect(
        [row(id="4", arxiv="1511.06233", title=TITLE)],
        web,
        existing={"4": manual},
        refresh=True,
    )
    assert results["4"] == manual
    assert web.requested == []


# --- the file ----------------------------------------------------------------------------


def test_the_file_round_trips_in_the_order_of_the_methods(tmp_path: Path) -> None:
    results = {
        "5": stored(
            source="arXiv", url="https://arxiv.org/abs/1506.06112", title="Src Five"
        ),
        "4": stored(
            LONG + ', with "quotes", commas',
            source="OpenAlex",
            url="https://openalex.org/W1",
            matched_by="doi",
            title="Src Four",
        ),
    }
    rows = [
        row(id="4", title="Title Four"),
        row(id="5", title="Title, Five"),
        row(id="6", title="Six"),
    ]
    path = tmp_path / "abstracts.csv"
    write_abstracts(path, rows, results)
    assert path.read_bytes().startswith(
        b"\xef\xbb\xbf"
    )  # a byte-order mark, for spreadsheets
    with path.open(newline="", encoding="utf-8-sig") as handle:
        written = list(csv.DictReader(handle))
    assert list(written[0]) == list(ABSTRACT_COLUMNS)
    assert [r["id"] for r in written] == [
        "4",
        "5",
    ]  # 6 has none; the order follows the rows
    assert [r["method_title"] for r in written] == ["Title Four", "Title, Five"]
    assert [r["source_title"] for r in written] == ["Src Four", "Src Five"]
    assert written[0]["abstract"].endswith('with "quotes", commas')
    back = read_abstracts(path)
    assert set(back) == {"4", "5"}
    assert back["5"].source == "arXiv"
    assert back["5"].matched_by == "arxiv id"
    assert back["5"].method_title == "Title, Five"
    assert back["5"].title == "Src Five"


def test_what_the_tool_writes_is_what_the_site_loads(tmp_path: Path) -> None:
    results = {
        "1": stored(),
        "2": stored(
            source="OpenAlex", url="https://openalex.org/W9", matched_by="title"
        ),
    }
    rows = [row(id="1", title=TITLE), row(id="2", title=TITLE)]
    path = tmp_path / "abstracts.csv"
    write_abstracts(path, rows, results)
    frame = load_abstracts(path)
    assert frame["id"].tolist() == ["1", "2"]


def test_a_failed_write_leaves_the_old_file_and_no_leftovers(tmp_path: Path) -> None:
    class Exploding:
        source, url, matched_by, title = "arXiv", "https://x.org", "doi", "t"

        @property
        def text(self) -> str:
            raise RuntimeError("boom")

    path = tmp_path / "abstracts.csv"
    path.write_text("old content", encoding="utf-8")
    with pytest.raises(RuntimeError):
        write_abstracts(path, [row(id="1")], {"1": Exploding()})  # type: ignore[dict-item]
    assert path.read_text(encoding="utf-8") == "old content"
    assert [p.name for p in tmp_path.iterdir()] == ["abstracts.csv"]


def test_if_the_final_rename_fails_the_old_file_is_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "abstracts.csv"
    path.write_text("old content", encoding="utf-8")

    def refuse(source: str, target: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError, match="disk full"):
        write_abstracts(path, [row(id="1")], {"1": stored()})
    assert path.read_text(encoding="utf-8") == "old content"
    assert [p.name for p in tmp_path.iterdir()] == ["abstracts.csv"]


def test_the_tool_writes_every_column_the_site_needs_in_the_same_order() -> None:
    assert [c for c in ABSTRACT_COLUMNS if c != "source_title"] == list(SITE_COLUMNS)
    assert abstract_parsing.MAX_ABSTRACT_CHARS == MAX_ABSTRACT_CHARS


def test_a_file_without_the_source_title_column_is_still_read(tmp_path: Path) -> None:
    path = tmp_path / "abstracts.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "id",
                "method_title",
                "abstract",
                "abstract_source",
                "abstract_url",
                "abstract_match",
            ]
        )
        writer.writerow(
            ["1", TITLE, LONG, "arXiv", "https://arxiv.org/abs/1511.06233", "arxiv id"]
        )
    found = read_abstracts(path)["1"]
    assert found.title == ""
    assert found.method_title == TITLE
    assert found.text == LONG
    assert len(load_abstracts(path)) == 1  # and the site loads it


def test_a_file_missing_a_needed_column_is_an_error_not_an_empty_result(
    tmp_path: Path,
) -> None:
    path = tmp_path / "abstracts.csv"
    path.write_text("id,abstract\n1,x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        read_abstracts(path)


def test_everything_the_tool_can_emit_is_accepted_by_the_site(tmp_path: Path) -> None:
    from tools import abstract_parsing as parsing

    crossref = json.dumps({"message": {"title": ["T"], "abstract": LONG}})
    emitted = [
        *parsing.parse_arxiv_atom(ATOM).values(),
        parsing.parse_openalex_work(openalex_work(), matched_by="title"),
        parsing.parse_crossref_work(crossref, "10.1/x"),
        parsing.parse_cvf(CVF_HTML, "https://openaccess.thecvf.com/x.html"),
        parsing.parse_pmlr(PMLR_HTML, "https://proceedings.mlr.press/x.html"),
    ]
    assert None not in emitted
    assert len(emitted) == 6
    rows = [row(id=str(n), title=f"Method {n}") for n in range(6)]
    results = {str(n): found for n, found in enumerate(emitted) if found}
    path = tmp_path / "abstracts.csv"
    write_abstracts(path, rows, results)
    frame = load_abstracts(path)  # the site's own validation
    assert len(frame) == 6
    assert set(frame["abstract_source"]) <= set(ABSTRACT_SOURCES)
    assert set(frame["abstract_match"]) <= set(ABSTRACT_MATCHES)


# --- the command line --------------------------------------------------------------------


def _write_methods(path: Path) -> None:
    fields = [
        "id",
        "method",
        "year",
        "authors_surnames",
        "title",
        "arxiv",
        "doi",
        "paper_url",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row(id="4", arxiv="1511.06233"))
        writer.writerow(
            row(id="5", title="A Paper Nobody Has Abstracts For", year="2001")
        )


def test_the_command_writes_the_file_reports_misses_and_is_incremental(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    methods, out = (
        tmp_path / "methods.csv",
        tmp_path / "data" / "abstracts.csv",
    )  # folder is new
    _write_methods(methods)
    web = FakeWeb(("export.arxiv.org/api/query?id_list", ATOM))
    monkeypatch.setattr(fetcher, "Web", lambda: web)
    caplog.set_level("INFO", logger="fetch_abstracts")

    assert fetcher.main(["--methods", str(methods), "--out", str(out)]) == 0
    assert set(read_abstracts(out)) == {"4"}
    assert "1 of 2 methods" in caplog.text
    assert "none found: 5" in caplog.text

    web.requested.clear()
    fetcher.main(["--methods", str(methods), "--out", str(out)])
    assert not [
        u for u in web.requested if "id_list" in u
    ]  # nothing new to fetch for 4
    web.requested.clear()
    fetcher.main(["--methods", str(methods), "--out", str(out), "--refresh"])
    assert [u for u in web.requested if "id_list" in u]


def test_refreshing_with_the_network_down_changes_nothing_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    methods, out = tmp_path / "methods.csv", tmp_path / "abstracts.csv"
    _write_methods(methods)
    other = "A Paper Nobody Has Abstracts For"
    manual = stored(
        "By hand. " * 20,
        source="Manual",
        url="https://example.org/p",
        matched_by="manual",
        method_title=other,
    )
    write_abstracts(
        out,
        [row(id="4", title=TITLE), row(id="5", title=other)],
        {"4": stored(), "5": manual},
    )

    def down(url: str) -> str | None:
        raise OSError("network down")

    monkeypatch.setattr(fetcher, "Web", lambda: down)
    code = fetcher.main(["--methods", str(methods), "--out", str(out), "--refresh"])
    assert code == 1  # something went wrong, and the exit code says so
    back = read_abstracts(out)
    assert set(back) == {"4", "5"}
    assert back["5"].source == "Manual"
    assert back["5"].text == manual.text.strip()  # tidied: no trailing space
    assert back["4"].text == LONG


def test_an_unreadable_input_stops_the_run_with_code_2_and_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    methods, out = tmp_path / "methods.csv", tmp_path / "abstracts.csv"
    _write_methods(methods)
    out.write_text("id,abstract\n1,x\n", encoding="utf-8")  # a damaged abstracts file
    monkeypatch.setattr(fetcher, "Web", lambda: FakeWeb())
    assert fetcher.main(["--methods", str(methods), "--out", str(out)]) == 2
    assert out.read_text(encoding="utf-8") == "id,abstract\n1,x\n"  # not overwritten
    assert (
        fetcher.main(["--methods", str(tmp_path / "nope.csv"), "--out", str(out)]) == 2
    )


def test_methods_with_a_repeated_or_empty_id_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "methods.csv"
    path.write_text(
        "id,year,title,authors_surnames,arxiv,doi,paper_url\n1,2016,A,X,,,\n1,2017,B,X,,,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="repeated id"):
        read_methods(path)


OTHER = "A Paper Nobody Has Abstracts For"


def hand(text: str = "Typed by hand. " * 20, *, title: str = OTHER) -> Abstract:
    return stored(
        text,
        source="Manual",
        url="https://example.org/p",
        matched_by="manual",
        method_title=title,
    )


def test_a_manual_line_for_a_retitled_method_stops_the_run_before_anything_is_fetched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    methods, out = tmp_path / "methods.csv", tmp_path / "abstracts.csv"
    _write_methods(methods)
    write_abstracts(
        out, [row(id="5", title="The Old Title")], {"5": hand(title="The Old Title")}
    )
    before = out.read_bytes()
    web = FakeWeb()
    monkeypatch.setattr(fetcher, "Web", lambda: web)
    caplog.set_level("INFO", logger="fetch_abstracts")
    assert fetcher.main(["--methods", str(methods), "--out", str(out)]) == 2
    assert web.requested == []  # nothing was fetched
    assert out.read_bytes() == before  # and the typed text is still there
    assert "id 5" in caplog.text
    assert "another title" in caplog.text


def test_a_manual_line_with_line_breaks_is_written_back_as_one_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    methods, out = tmp_path / "methods.csv", tmp_path / "abstracts.csv"
    _write_methods(methods)
    with out.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "id",
                "method_title",
                "abstract",
                "abstract_source",
                "abstract_url",
                "abstract_match",
            ]
        )
        writer.writerow(
            [
                "5",
                OTHER,
                "Pasted from a PDF,\nwith a line break. " * 5,
                "Manual",
                "https://example.org/p",
                "manual",
            ]
        )
    monkeypatch.setattr(fetcher, "Web", lambda: FakeWeb())
    fetcher.main(["--methods", str(methods), "--out", str(out)])
    frame = load_abstracts(out)  # the site accepts it
    assert (
        frame.set_index("id")
        .loc["5", "abstract"]
        .startswith("Pasted from a PDF, with a line break.")
    )


def test_a_manual_line_added_while_the_tool_runs_is_not_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    methods, out = tmp_path / "methods.csv", tmp_path / "abstracts.csv"
    _write_methods(methods)
    first_call = {"done": False}

    def web(url: str) -> str | None:
        if not first_call[
            "done"
        ]:  # the author types an abstract while the tool is busy
            first_call["done"] = True
            write_abstracts(
                out, [row(id="5", title=OTHER)], {"5": hand("Added meanwhile. " * 20)}
            )
        return ATOM if "id_list" in url else None

    monkeypatch.setattr(fetcher, "Web", lambda: web)
    assert fetcher.main(["--methods", str(methods), "--out", str(out)]) == 0
    back = read_abstracts(out)
    assert set(back) == {"4", "5"}
    assert back["5"].source == "Manual"
    assert back["5"].text.startswith("Added meanwhile.")


def test_a_manual_line_added_during_the_run_that_does_not_fit_is_reported_and_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    methods, out = tmp_path / "methods.csv", tmp_path / "abstracts.csv"
    _write_methods(methods)
    added = {"done": False}

    def web(url: str) -> str | None:
        if not added["done"]:
            added["done"] = True
            write_abstracts(
                out,
                [row(id="5", title="Some Other Title")],
                {"5": hand(title="Some Other Title")},
            )
        return ATOM if "id_list" in url else None

    monkeypatch.setattr(fetcher, "Web", lambda: web)
    caplog.set_level("WARNING", logger="fetch_abstracts")
    assert fetcher.main(["--methods", str(methods), "--out", str(out)]) == 0
    assert set(read_abstracts(out)) == {
        "4"
    }  # the odd line is not written, the run is whole
    assert "added during the run was not kept" in caplog.text


def test_an_edit_to_a_manual_line_during_the_run_wins_over_the_old_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    methods, out = tmp_path / "methods.csv", tmp_path / "abstracts.csv"
    _write_methods(methods)
    write_abstracts(
        out, [row(id="5", title=OTHER)], {"5": hand("First version. " * 20)}
    )
    edited = {"done": False}

    def web(url: str) -> str | None:
        if not edited["done"]:
            edited["done"] = True
            write_abstracts(
                out, [row(id="5", title=OTHER)], {"5": hand("Second version. " * 20)}
            )
        return ATOM if "id_list" in url else None

    monkeypatch.setattr(fetcher, "Web", lambda: web)
    fetcher.main(["--methods", str(methods), "--out", str(out)])
    assert read_abstracts(out)["5"].text.startswith("Second version.")


def test_if_the_file_is_damaged_during_the_run_the_results_go_to_a_side_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    methods, out = tmp_path / "methods.csv", tmp_path / "abstracts.csv"
    _write_methods(methods)
    damaged = {"done": False}

    def web(url: str) -> str | None:
        if not damaged["done"]:
            damaged["done"] = True
            out.write_text("id,abstract\n1,x\n", encoding="utf-8")  # someone broke it
        return ATOM if "id_list" in url else None

    monkeypatch.setattr(fetcher, "Web", lambda: web)
    assert fetcher.main(["--methods", str(methods), "--out", str(out)]) == 2
    assert out.read_text(encoding="utf-8") == "id,abstract\n1,x\n"  # not overwritten
    assert set(read_abstracts(tmp_path / "abstracts.csv.new")) == {
        "4"
    }  # nothing fetched is lost


def test_an_interrupt_keeps_what_was_found_so_far(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    methods, out = tmp_path / "methods.csv", tmp_path / "abstracts.csv"
    fields = [
        "id",
        "method",
        "year",
        "authors_surnames",
        "title",
        "arxiv",
        "doi",
        "paper_url",
    ]
    with methods.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for number in (1, 2, 3):
            writer.writerow(
                row(id=str(number), title=f"Paper {number}", doi=f"10.1/p{number}")
            )
        writer.writerow(row(id="4", title="Paper 4", doi="10.1/p4"))

    def web(url: str) -> str | None:
        if "p3" in url:
            raise KeyboardInterrupt
        if "doi:10.1/p" in url:
            number = url.split("doi:10.1/p")[1][0]
            return openalex_work(title=f"Paper {number}")
        return None

    monkeypatch.setattr(fetcher, "Web", lambda: web)
    monkeypatch.setattr(fetcher, "CHECKPOINT_EVERY", 1)
    assert fetcher.main(["--methods", str(methods), "--out", str(out)]) == 130
    assert set(read_abstracts(out)) == {"1", "2"}


def test_a_failure_to_write_is_reported_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    methods, out = tmp_path / "methods.csv", tmp_path / "abstracts.csv"
    _write_methods(methods)

    def full_disk(path: Path, rows: object, results: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(fetcher, "Web", lambda: FakeWeb(("id_list", ATOM)))
    monkeypatch.setattr(fetcher, "write_abstracts", full_disk)
    caplog.set_level("ERROR", logger="fetch_abstracts")
    assert fetcher.main(["--methods", str(methods), "--out", str(out)]) == 2
    assert "could not be written" in caplog.text
    assert "disk full" in caplog.text


def test_the_written_file_keeps_the_mode_of_the_old_one_and_a_new_one_is_readable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "abstracts.csv"
    write_abstracts(path, [row(id="1")], {"1": stored()})
    assert path.stat().st_mode & 0o777 == 0o644  # not the 0600 of a temporary file
    path.chmod(0o640)
    write_abstracts(path, [row(id="1")], {"1": stored()})
    assert path.stat().st_mode & 0o777 == 0o640


def test_a_find_whose_link_is_not_its_sources_own_is_never_stored() -> None:
    assert storable(stored())
    assert not storable(stored(url=f"https://arxiv.org{AT}evil.example/abs/1"))
    assert not storable(stored(source="OpenAlex", url="https://evil.example/W1"))
    assert not storable(stored(source="OpenAlex", url="https://arxiv.org/abs/1"))
    assert any("link" in p for p in line_problems(stored(url="https:///x")))


def test_a_short_row_in_the_abstracts_file_is_refetched_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    methods, out = tmp_path / "methods.csv", tmp_path / "abstracts.csv"
    _write_methods(methods)
    header = "id,method_title,abstract,abstract_source,abstract_url,abstract_match"
    out.write_text(f"{header}\n4,{TITLE}\n", encoding="utf-8")  # the row stops early
    monkeypatch.setattr(fetcher, "Web", lambda: FakeWeb(("id_list", ATOM)))
    assert fetcher.main(["--methods", str(methods), "--out", str(out)]) == 0
    assert read_abstracts(out)["4"].text == LONG


def test_a_short_row_in_the_methods_file_gives_empty_cells_not_none(
    tmp_path: Path,
) -> None:
    path = tmp_path / "methods.csv"
    path.write_text(
        "id,year,title,authors_surnames,arxiv,doi,paper_url\n7,2016\n", encoding="utf-8"
    )
    assert read_methods(path) == [
        {
            "id": "7",
            "year": "2016",
            "title": "",
            "authors_surnames": "",
            "arxiv": "",
            "doi": "",
            "paper_url": "",
        }
    ]
