"""Loading abstracts and attaching them to the methods."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from explorer.abstracts import (
    attach_abstracts,
    collection_version,
    load_abstracts,
    load_collection,
)
from explorer.constants import ABSTRACT_FIELDS
from explorer.data import DataError
from tests.abstract_fixtures import AT
from tests.conftest import (
    make_abstract,
    make_frame,
    make_row,
    write_abstracts_csv,
    write_csv,
)

pytestmark = pytest.mark.unit


def test_a_missing_file_means_no_abstracts(tmp_path: Path) -> None:
    frame = load_abstracts(tmp_path / "abstracts.csv")
    assert frame.empty
    assert list(frame.columns) == ["id", "method_title", *ABSTRACT_FIELDS]


def test_a_valid_file_is_read_as_text(tmp_path: Path) -> None:
    path = write_abstracts_csv(
        tmp_path / "abstracts.csv", make_abstract(id="N3"), make_abstract(id="12")
    )
    frame = load_abstracts(path)
    assert frame["id"].tolist() == ["N3", "12"]
    assert frame.loc[0, "abstract_source"] == "arXiv"


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"abstract": ""}, "abstract"),
        ({"abstract": "   "}, "abstract"),
        ({"abstract": "line one\nline two " * 10}, "line break"),
        ({"abstract": "x" * 8001}, "long"),
        ({"abstract_source": "Wikipedia"}, "abstract_source"),
        ({"abstract_match": "guess"}, "abstract_match"),
        ({"abstract_url": "javascript:alert(1)"}, "abstract_url"),
        ({"abstract_url": ""}, "abstract_url"),
        ({"abstract_url": f"https://arxiv.org{AT}evil.example/abs/1"}, "abstract_url"),
        ({"abstract_url": f"https://user:pw{AT}arxiv.org/abs/1"}, "abstract_url"),
        ({"abstract_url": "http://arxiv.org/abs/1"}, "abstract_url"),
        ({"abstract_url": "https://evil.example/abs/1"}, "abstract_url"),
        (
            {"abstract_url": "https://openalex.org/W1"},
            "abstract_url",
        ),  # not arXiv's site
        ({"abstract_url": "https:///abs/1"}, "abstract_url"),
        ({"abstract_url": "https://arxiv.org/abs/" + "1" * 3000}, "abstract_url"),
        ({"id": "has space"}, "id"),
        ({"method_title": ""}, "method_title"),
    ],
)
def test_an_invalid_line_is_a_data_error_naming_the_column(
    tmp_path: Path, overrides: dict[str, str], needle: str
) -> None:
    path = write_abstracts_csv(tmp_path / "abstracts.csv", make_abstract(**overrides))
    with pytest.raises(DataError, match=needle):
        load_abstracts(path)


def test_duplicate_ids_are_a_data_error(tmp_path: Path) -> None:
    path = write_abstracts_csv(
        tmp_path / "abstracts.csv", make_abstract(id="7"), make_abstract(id="7")
    )
    with pytest.raises(DataError, match="duplicate"):
        load_abstracts(path)


def test_a_missing_column_is_a_data_error(tmp_path: Path) -> None:
    path = tmp_path / "abstracts.csv"
    pd.DataFrame({"id": ["1"], "abstract": ["x" * 120]}).to_csv(path, index=False)
    with pytest.raises(DataError, match="abstract_source"):
        load_abstracts(path)


def test_error_messages_name_the_file_not_its_folder(tmp_path: Path) -> None:
    path = write_abstracts_csv(tmp_path / "abstracts.csv", make_abstract(abstract=""))
    with pytest.raises(DataError) as caught:
        load_abstracts(path)
    assert "abstracts.csv" in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


# --- attaching ------------------------------------------------------------------------


def test_abstracts_are_attached_by_id_and_the_rest_are_empty() -> None:
    methods = make_frame(
        make_row(id="1", title="A Title"), make_row(id="2", title="Another")
    )
    abstracts = pd.DataFrame([make_abstract(id="2", method_title="Another")])
    joined = attach_abstracts(methods, abstracts)
    assert joined["id"].tolist() == ["1", "2"]  # the order of the methods
    assert joined.loc[0, "abstract"] == ""
    assert joined.loc[0, "abstract_source"] == ""
    assert joined.loc[1, "abstract"].startswith("This is an abstract")
    assert joined.loc[1, "abstract_source"] == "arXiv"


def test_attaching_does_not_change_its_inputs() -> None:
    methods = make_frame(make_row(id="1", title="A Title"))
    abstracts = pd.DataFrame([make_abstract(id="1")])
    before = methods.copy(deep=True)
    attach_abstracts(methods, abstracts)
    assert methods.equals(before)
    assert "abstract" not in methods.columns


def test_every_abstract_field_is_present_even_when_there_are_no_abstracts() -> None:
    methods = make_frame(make_row(id="1"))
    joined = attach_abstracts(
        methods, load_abstracts(Path("/nonexistent/abstracts.csv"))
    )
    for name in ABSTRACT_FIELDS:
        assert joined[name].tolist() == [""]


def test_a_file_whose_only_line_is_for_an_unknown_id_is_refused() -> None:
    methods = make_frame(make_row(id="1", title="A Title"))
    abstracts = pd.DataFrame([make_abstract(id="99")])
    with pytest.raises(DataError, match="99"):
        attach_abstracts(methods, abstracts)


def test_a_file_whose_only_line_is_for_another_title_is_refused() -> None:
    """If the ids were renumbered, id 1 is another paper now: never show its old abstract."""
    methods = make_frame(make_row(id="1", title="The Paper Now Called One"))
    abstracts = pd.DataFrame(
        [make_abstract(id="1", method_title="The Paper Once Called One")]
    )
    with pytest.raises(DataError, match="fetch_abstracts"):
        attach_abstracts(methods, abstracts)


def test_one_stale_line_is_left_out_with_a_warning_and_the_site_still_loads(
    caplog: pytest.LogCaptureFixture,
) -> None:
    methods = make_frame(
        *(make_row(id=str(i), title=f"Title {i}") for i in range(1, 6))
    )
    abstracts = pd.DataFrame(
        [
            make_abstract(id="1", method_title="Title 1"),
            make_abstract(id="2", method_title="Title 2, as it was before"),
            make_abstract(id="3", method_title="Title 3"),
            make_abstract(id="99", method_title="No such method"),
        ]
    )
    caplog.set_level("WARNING", logger="explorer.abstracts")
    joined = attach_abstracts(methods, abstracts)
    assert joined["abstract_source"].tolist() == ["arXiv", "", "arXiv", "", ""]
    assert "2" in caplog.text
    assert "99" in caplog.text
    assert "fetch_abstracts" in caplog.text


def test_when_most_lines_do_not_fit_the_file_belongs_to_another_collection() -> None:
    methods = make_frame(
        *(make_row(id=str(i), title=f"Title {i}") for i in range(1, 5))
    )
    lines = [
        make_abstract(id=str(i), method_title=f"Old title {i}") for i in range(1, 4)
    ]
    lines.append(make_abstract(id="4", method_title="Title 4"))
    with pytest.raises(DataError, match="fetch_abstracts"):
        attach_abstracts(methods, pd.DataFrame(lines))


def test_exactly_half_stale_lines_is_still_tolerated() -> None:
    methods = make_frame(
        *(make_row(id=str(i), title=f"Title {i}") for i in range(1, 5))
    )
    lines = [make_abstract(id=str(i), method_title=f"Title {i}") for i in (1, 2)]
    lines += [make_abstract(id=str(i), method_title="Other") for i in (3, 4)]
    joined = attach_abstracts(methods, pd.DataFrame(lines))
    assert joined["abstract_source"].tolist() == ["arXiv", "arXiv", "", ""]


# --- knowing when the files changed ---------------------------------------------------


def test_the_version_changes_when_either_file_changes_or_appears(
    tmp_path: Path,
) -> None:
    methods = write_csv(tmp_path / "methods.csv", make_row(id="1"))
    start = collection_version(methods)
    assert collection_version(methods) == start  # stable while nothing changes
    abstracts = write_abstracts_csv(tmp_path / "abstracts.csv", make_abstract(id="1"))
    with_file = collection_version(methods)
    assert with_file != start  # the abstracts file appeared
    abstracts.write_bytes(abstracts.read_bytes() + b"\n")  # a different size
    assert collection_version(methods) != with_file
    abstracts.unlink()
    assert collection_version(methods) == start  # and went away again


def test_a_file_changed_without_a_new_time_is_noticed_by_its_size(
    tmp_path: Path,
) -> None:
    path = write_csv(tmp_path / "methods.csv", make_row(id="1"))
    stat = path.stat()
    before = collection_version(path)
    path.write_bytes(path.read_bytes() + b"\n")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # the old time, put back
    assert collection_version(path) != before


def test_a_file_replaced_by_an_older_one_of_the_same_size_is_noticed(
    tmp_path: Path,
) -> None:
    path = write_csv(tmp_path / "methods.csv", make_row(id="1"))
    before = collection_version(path)
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns - 5_000_000_000))  # 5 s older
    assert collection_version(path) != before


def test_the_version_of_a_missing_methods_file_is_not_an_error(tmp_path: Path) -> None:
    assert collection_version(tmp_path / "nope.csv") == collection_version(
        tmp_path / "nope.csv"
    )


# --- the whole collection -------------------------------------------------------------


def test_the_collection_reads_the_abstracts_file_next_to_the_methods(
    tmp_path: Path,
) -> None:
    write_csv(tmp_path / "methods.csv", make_row(id="1", title="A Title"))
    write_abstracts_csv(tmp_path / "abstracts.csv", make_abstract(id="1"))
    frame = load_collection(tmp_path / "methods.csv")
    assert frame.loc[0, "abstract_source"] == "arXiv"


def test_without_an_abstracts_file_the_collection_still_loads(tmp_path: Path) -> None:
    write_csv(tmp_path / "methods.csv", make_row(id="1"))
    frame = load_collection(tmp_path / "methods.csv")
    assert frame.loc[0, "abstract"] == ""


def test_a_long_list_of_problems_is_cut_short(tmp_path: Path) -> None:
    lines = [make_abstract(id=str(i), abstract="") for i in range(30)]
    path = write_abstracts_csv(tmp_path / "abstracts.csv", *lines)
    with pytest.raises(DataError, match="and 20 more"):
        load_abstracts(path)


@pytest.mark.parametrize(
    ("source", "url"),
    [
        ("OpenAlex", "https://openalex.org/W2119880843"),
        ("OpenAlex", "https://doi.org/10.1109/tpami.2012.256"),
        ("Crossref", "https://doi.org/10.1/x"),
        ("CVF", "https://openaccess.thecvf.com/content/CVPR2021/html/x.html"),
        ("PMLR", "https://proceedings.mlr.press/v199/x.html"),
        ("Manual", "http://example.org/p"),  # typed by a person: any site, even http
        ("Manual", "https://anything.example/page?x=1"),
    ],
)
def test_a_link_on_the_sources_own_site_is_accepted(
    tmp_path: Path, source: str, url: str
) -> None:
    match = "manual" if source == "Manual" else "doi"
    line = make_abstract(abstract_source=source, abstract_url=url, abstract_match=match)
    assert (
        len(load_abstracts(write_abstracts_csv(tmp_path / "abstracts.csv", line))) == 1
    )


def test_a_manual_line_still_needs_a_real_host_and_no_user_name(tmp_path: Path) -> None:
    for url in ("https:///x", f"https://user{AT}example.org/p", "ftp://example.org/p"):
        line = make_abstract(
            abstract_source="Manual", abstract_url=url, abstract_match="manual"
        )
        with pytest.raises(DataError, match="abstract_url"):
            load_abstracts(write_abstracts_csv(tmp_path / "abstracts.csv", line))


def test_an_error_message_never_repeats_a_huge_value(tmp_path: Path) -> None:
    line = make_abstract(id="x" * 100_000, abstract_url="y" * 100_000)
    with pytest.raises(DataError) as caught:
        load_abstracts(write_abstracts_csv(tmp_path / "abstracts.csv", line))
    assert len(str(caught.value)) < 2_000


def test_the_site_and_the_tool_use_the_same_link_rule() -> None:
    """The two sides must refuse and accept the same links."""
    from explorer.abstracts import url_problem as site_rule
    from tools.abstract_parsing import url_problem as tool_rule

    for source in ("arXiv", "OpenAlex", "Crossref", "CVF", "PMLR", "Manual"):
        for url in LINKS:
            assert bool(site_rule(source, url)) == bool(tool_rule(source, url)), (
                source,
                url,
            )


LINKS = [
    "https://arxiv.org/abs/1", "http://arxiv.org/abs/1", f"https://arxiv.org{AT}evil.example/x",
    f"https://user:pw{AT}arxiv.org/x", "https:///x", "https://?x", "https://#", "https://arxiv.org:8443/x",
    "https://arxiv.org:443/abs/1", "https://openalex.org/W1", "https://doi.org/10.1/x",
    "https://openaccess.thecvf.com/x", "https://proceedings.mlr.press/x", "https://example.org/p",
    "http://example.org/p", "javascript:alert(1)", "ftp://example.org/p", "", "https://a b/x",
    "https://example.org:notaport/p", "https://example.org/" + "a" * 2100, "HTTPS://ARXIV.ORG/abs/1",
]  # fmt: skip
