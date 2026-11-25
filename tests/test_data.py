"""Loading, validating and preparing the public methods table."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from explorer.constants import PUBLIC_COLUMNS
from explorer.data import DataError, load_methods, prepare_methods
from tests.conftest import make_raw_frame, make_row, write_csv

pytestmark = pytest.mark.unit


def _load(tmp_path: Path, *rows: dict[str, str]) -> pd.DataFrame:
    return load_methods(write_csv(tmp_path / "m.csv", *rows))


# --- reading --------------------------------------------------------------------------


def test_reads_bom_csv_with_public_columns_first(tmp_path: Path) -> None:
    frame = _load(tmp_path, make_row())
    assert list(frame.columns[: len(PUBLIC_COLUMNS)]) == list(PUBLIC_COLUMNS)
    assert frame.columns[0] == "id"  # the byte-order mark is not part of the name


def test_reads_csv_without_bom(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "m.csv", make_row(), bom=False)
    assert load_methods(path).loc[0, "id"] == "1"


def test_ids_and_every_cell_stay_text(tmp_path: Path) -> None:
    frame = _load(
        tmp_path, make_row(id="N3", year="2023"), make_row(id="10", year="2020")
    )
    assert frame["id"].tolist() == ["N3", "10"]
    assert all(isinstance(value, str) for value in frame["year"])


def test_literal_na_like_text_is_not_turned_into_missing_values(tmp_path: Path) -> None:
    row = make_row(method="NA", authors_surnames="None", title="null", venue="N/A")
    frame = _load(tmp_path, row)
    assert frame.loc[0, "method"] == "NA"
    assert frame.loc[0, "authors_surnames"] == "None"
    assert frame.loc[0, "title"] == "null"
    assert frame.loc[0, "venue"] == "N/A"


def test_empty_cells_are_empty_strings(tmp_path: Path) -> None:
    frame = _load(tmp_path, make_row(doi="", arxiv=""))
    assert frame.loc[0, "doi"] == ""
    assert frame.loc[0, "arxiv"] == ""


def test_extra_columns_are_not_carried_into_the_table(tmp_path: Path) -> None:
    raw = make_raw_frame(make_row()).assign(note="internal wording", code_evidence="x")
    path = tmp_path / "m.csv"
    raw.to_csv(path, index=False, encoding="utf-8-sig")
    frame = load_methods(path)
    assert "note" not in frame.columns
    assert "code_evidence" not in frame.columns


def test_row_order_follows_the_file(tmp_path: Path) -> None:
    frame = _load(tmp_path, make_row(id="b"), make_row(id="a"), make_row(id="c"))
    assert frame["id"].tolist() == ["b", "a", "c"]


# --- validation -----------------------------------------------------------------------


def test_missing_file_is_a_data_error(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="not found"):
        load_methods(tmp_path / "absent.csv")


def test_header_only_file_is_a_data_error(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="no rows"):
        _load(tmp_path)


@pytest.mark.parametrize(
    ("content", "needle"),
    [
        (b"\xff\xfe\x81bad bytes", "could not be read"),  # not UTF-8
        (b"", "could not be read"),  # nothing at all, not even a header
        (b"a,b\n1,2\n1,2,3\n", "could not be read"),  # a later row with too many fields
    ],
)
def test_unreadable_files_are_a_data_error(
    tmp_path: Path, content: bytes, needle: str
) -> None:
    path = tmp_path / "broken.csv"
    path.write_bytes(content)
    with pytest.raises(DataError, match=needle):
        load_methods(path)


def test_missing_column_is_a_data_error(tmp_path: Path) -> None:
    raw = make_raw_frame(make_row()).drop(columns=["tree_section"])
    path = tmp_path / "m.csv"
    raw.to_csv(path, index=False)
    with pytest.raises(DataError, match="tree_section"):
        load_methods(path)


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"id": ""}, "id"),
        ({"tree_family": ""}, "tree_family"),
        ({"tree_section": " "}, "tree_section"),
        ({"method": ""}, "method"),
        ({"year": "20x0"}, "year"),
        ({"year": ""}, "year"),
        ({"code_type": "forked"}, "code_type"),
        ({"check": "X"}, "check"),
        ({"authors_complete": "maybe"}, "authors_complete"),
        ({"paper_url": "javascript:alert(1)"}, "paper_url"),
        ({"paper_url": "ftp://example.org/a"}, "paper_url"),
        ({"code_url": "https://x.org/a b", "code_type": "official"}, "code_url"),
        (
            {
                "code_alt": "library|ftp://example.org/x",
                "code_type": "official",
                "code_url": "https://a.org/b",
            },
            "code_alt",
        ),
        (
            {
                "code_alt": "nonsense",
                "code_type": "official",
                "code_url": "https://a.org/b",
            },
            "code_alt",
        ),
    ],
)
def test_invalid_cell_is_a_data_error_naming_the_column(
    tmp_path: Path, overrides: dict[str, str], needle: str
) -> None:
    with pytest.raises(DataError, match=needle):
        _load(tmp_path, make_row(**overrides))


def test_duplicate_ids_are_a_data_error(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="duplicate"):
        _load(tmp_path, make_row(id="7"), make_row(id="7"))


def test_code_type_and_code_url_must_agree(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="code_url"):
        _load(tmp_path, make_row(code_type="official", code_url=""))
    with pytest.raises(DataError, match="code_url"):
        _load(tmp_path, make_row(code_type="none", code_url="https://a.org/b"))


def test_alternative_code_needs_a_primary_code_link(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="code_alt"):
        _load(
            tmp_path,
            make_row(code_type="none", code_url="", code_alt="library|https://a.org/b"),
        )


def test_error_message_names_every_offending_row(tmp_path: Path) -> None:
    rows = (
        make_row(id="A1", year="x"),
        make_row(id="A2", check="Z"),
        make_row(id="A3"),
    )
    with pytest.raises(DataError) as caught:
        _load(tmp_path, *rows)
    message = str(caught.value)
    assert "A1" in message
    assert "A2" in message
    assert "A3" not in message


def test_error_message_is_capped(tmp_path: Path) -> None:
    rows = [make_row(id=str(i), year="bad") for i in range(40)]
    with pytest.raises(DataError) as caught:
        _load(tmp_path, *rows)
    assert "more" in str(caught.value)


# --- preparation ----------------------------------------------------------------------


def test_year_num_is_numeric(tmp_path: Path) -> None:
    frame = _load(tmp_path, make_row(year="1954"), make_row(id="2", year="2026"))
    assert frame["year_num"].tolist() == [1954, 2026]
    assert pd.api.types.is_integer_dtype(frame["year_num"])


def test_search_text_holds_folded_method_authors_and_title_only(tmp_path: Path) -> None:
    row = make_row(
        method="Halász X",
        authors_surnames="Candès; de Rezende Rocha",
        title="Open–Set Recognition",
        venue="SECRETVENUE",
        doi="10.1/doi-only",
    )
    text = _load(tmp_path, row).loc[0, "search_text"]
    assert text == "halasz x candes de rezende rocha open set recognition"


def test_prepare_does_not_mutate_its_input() -> None:
    raw = make_raw_frame(make_row())
    before = raw.copy(deep=True)
    prepared = prepare_methods(raw)
    assert raw.equals(before)
    assert list(raw.columns) == list(PUBLIC_COLUMNS)
    assert prepared is not raw


# --- hardening found in review ---------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    ["x" * 33, "has space", "family:Unknown", "a/b", "a;b", "né", "4\n5", "<b>"],
)
def test_an_id_must_be_short_and_made_of_plain_characters(
    tmp_path: Path, bad_id: str
) -> None:
    """Ids go into the address (?m=) and into folder ids: keep them tame."""
    with pytest.raises(DataError, match="id"):
        _load(tmp_path, make_row(id=bad_id))


@pytest.mark.parametrize("good_id", ["1", "162", "N8", "a.b-c_d", "x" * 32])
def test_plain_ids_are_accepted(tmp_path: Path, good_id: str) -> None:
    assert _load(tmp_path, make_row(id=good_id)).loc[0, "id"] == good_id


@pytest.mark.parametrize("column", ["method", "authors_surnames", "title", "venue"])
@pytest.mark.parametrize(
    "value",
    ["two\nlines", "a\rb", "tab\there", "bidi ‮ text", "zero​width"],
)
def test_text_cells_may_not_hold_line_breaks_or_control_characters(
    tmp_path: Path, column: str, value: str
) -> None:
    with pytest.raises(DataError, match=f"{column}.*control|{column}.*line break"):
        _load(tmp_path, make_row(**{column: value}))


@pytest.mark.parametrize("column", ["method", "authors_surnames", "title", "venue"])
@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("see https://example.org/x", "web address"),
        ("see HTTP://EXAMPLE.ORG", "web address"),
        ("www.example.org", "web address"),
        ("someone@example.org", "@"),
        ("a :smile: b", "emoji"),
        (":material/home:", "emoji"),
    ],
)
def test_text_cells_may_not_hold_what_markdown_would_turn_into_links_or_emoji(
    tmp_path: Path, column: str, value: str, reason: str
) -> None:
    with pytest.raises(DataError, match=reason):
        _load(tmp_path, make_row(**{column: value}))


def test_ordinary_colons_and_dots_in_text_are_fine(tmp_path: Path) -> None:
    row = make_row(
        title="SensorSCAN: Self-supervised learning, v2.0 (e.g. 3:2 ratio)",
        venue="IEEE TPAMI 35(7):1757–1772",
        method="Gibbs & Candès (2021)",
    )
    assert len(_load(tmp_path, row)) == 1


def test_a_year_must_be_ascii_digits(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="year"):
        _load(tmp_path, make_row(year="٢٠٢٠"))


def test_padded_values_are_reported(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="whitespace"):
        _load(tmp_path, make_row(method=" padded"))


def test_a_directory_instead_of_a_file_is_a_data_error(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="could not be read"):
        load_methods(tmp_path)


def test_error_messages_never_show_the_folder_the_file_is_in(tmp_path: Path) -> None:
    for path in (tmp_path / "absent.csv", tmp_path):
        with pytest.raises(DataError) as caught:
            load_methods(path)
        assert str(tmp_path.parent) not in str(caught.value)
    write_csv(tmp_path / "empty.csv")
    with pytest.raises(DataError) as caught:
        load_methods(tmp_path / "empty.csv")
    assert str(tmp_path) not in str(caught.value)
    assert "empty.csv" in str(caught.value)


@pytest.mark.parametrize("where", ["in a cell", "after the data", "before the header"])
def test_a_nul_byte_anywhere_in_the_file_is_a_data_error(
    tmp_path: Path, where: str
) -> None:
    """Older pandas silently cuts a cell at a NUL byte; no version may accept it."""
    good = write_csv(tmp_path / "good.csv", make_row(title="Some title")).read_bytes()
    broken = {
        "in a cell": good.replace(b"Some title", b"Some\x00title"),
        "after the data": good + b"\x00",
        "before the header": b"\x00" + good,
    }[where]
    path = tmp_path / "nul.csv"
    path.write_bytes(broken)
    with pytest.raises(DataError, match="NUL"):
        load_methods(path)
