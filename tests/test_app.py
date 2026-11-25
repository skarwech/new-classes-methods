"""Whole-script tests with Streamlit's AppTest.

AppTest can neither render nor click a custom component, so the tree is replaced by a recorder.
These tests pin down what the app asks of the tree, what it shows next to it, and how the
selection, the address and the filters interact. Clicking itself is covered in tests/e2e.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from explorer import text
from explorer.card import card_markdown, reference_text
from explorer.constants import TREE_HEIGHT, TREE_INDENT, TREE_ROW_HEIGHT
from explorer.tree import family_id, section_id, type_id
from tests.conftest import CSV_PATH, SITE_ROOT, make_row, write_csv

pytestmark = pytest.mark.integration

APP = SITE_ROOT / "app.py"


class TreeRecorder:
    """Stands in for the tree component and remembers every call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, data: list[dict], **kwargs: Any) -> None:
        self.calls.append({"data": data, **kwargs})
        return None

    @property
    def last(self) -> dict[str, Any]:
        return self.calls[-1]


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    st.cache_data.clear()


@pytest.fixture
def tree(monkeypatch: pytest.MonkeyPatch) -> TreeRecorder:
    recorder = TreeRecorder()
    monkeypatch.setattr("streamlit_arborist.tree_view", recorder)
    return recorder


def new_app(script: Path = APP) -> AppTest:
    return AppTest.from_file(str(script), default_timeout=30)


def main_markdown(at: AppTest) -> list[str]:
    return [element.value for element in at.main.markdown]


def sidebar_markdown(at: AppTest) -> list[str]:
    return [element.value for element in at.sidebar.markdown]


def card_text(at: AppTest) -> str:
    return "\n".join(main_markdown(at))


def card_column_markdown(at: AppTest) -> list[str]:
    """Markdown in the right-hand column only (the card), not the top expander."""
    return [element.value for element in at.columns[1].markdown]


def selected_card(at: AppTest) -> str:
    """The markdown of the detail card itself (the element that starts with a heading)."""
    return next(value for value in main_markdown(at) if value.startswith("### "))


def folder_names(nodes: list[dict]) -> list[str]:
    return [node["name"] for node in nodes]


# --- the first screen -----------------------------------------------------------------


def test_default_run_shows_the_header_the_counter_and_a_collapsed_tree(
    tree: TreeRecorder,
) -> None:
    at = new_app().run()
    assert not at.exception
    assert at.title[0].value == text.TITLE
    assert text.description(170) in main_markdown(at)
    assert at.expander[0].label == "How to read"
    assert f"**{text.count_text(170, 170)}**" in sidebar_markdown(at)
    call = tree.last
    assert call["open_by_default"] is False
    assert call["selection"] is None
    assert call["initial_open_state"] is None
    assert (call["height"], call["row_height"], call["indent"]) == (
        TREE_HEIGHT,
        TREE_ROW_HEIGHT,
        TREE_INDENT,
    )
    assert call["key"].startswith("tree-")
    assert callable(call["on_change"])
    assert "icons" not in call  # plain-text icons would raise
    assert folder_names(call["data"]) == [
        "Unknown Rejection (63)",
        "Class Discovery (31)",
        "Model Integration (23)",
        "Stream Adaptation (43)",
        "Pipeline component references (10)",
    ]


def test_nothing_selected_shows_the_how_to_read_text_in_the_card(
    tree: TreeRecorder,
) -> None:
    at = new_app().run()
    assert card_column_markdown(at) == [text.HOW_TO_READ]
    assert not at.code  # no reference block without a selection


def test_how_to_read_is_also_in_the_top_expander(tree: TreeRecorder) -> None:
    at = new_app().run()
    assert text.HOW_TO_READ in [element.value for element in at.expander[0].markdown]


# --- the sidebar ----------------------------------------------------------------------


def test_sidebar_widgets_and_year_bounds_come_from_the_data(tree: TreeRecorder) -> None:
    at = new_app().run()
    assert at.text_input(key="q").value == ""
    assert list(at.multiselect(key="families").options) == [
        "Unknown Rejection",
        "Class Discovery",
        "Model Integration",
        "Stream Adaptation",
        "Pipeline component references",
    ]
    assert at.multiselect(key="code_types").options == [
        "Official code",
        "Third-party implementation",
        "Library implementation",
        "No public code found",
    ]
    assert at.multiselect(key="checks").options == [
        "Checked against the source",
        "Not re-checked",
        "Incomplete or flagged",
    ]
    year = at.slider(key="years")
    assert (year.min, year.max, year.value) == (1954, 2026, (1954, 2026))


def test_search_narrows_the_tree_the_counter_and_opens_every_folder(
    tree: TreeRecorder,
) -> None:
    at = new_app().run()
    default_key = tree.last["key"]
    at.text_input(key="q").set_value("halász").run()
    assert not at.exception
    assert f"**{text.count_text(2, 170)}**" in sidebar_markdown(at)
    call = tree.last
    assert (
        call["key"] != default_key
    )  # a new key remounts the tree so that the folders open
    assert folder_names(call["data"]) == ["Unknown Rejection (2)"]
    unknown = "Unknown Rejection"
    section_1_1 = "1.1 Discriminative Open Set Recognition"
    assert set(call["initial_open_state"]) == {
        family_id(unknown),
        section_id(unknown, section_1_1),
        type_id(unknown, section_1_1, "Time-series-specific"),
        section_id(unknown, "1.2 Generative Open Set Recognition"),
    }
    assert all(call["initial_open_state"].values())


def test_candes_finds_one_method(tree: TreeRecorder) -> None:
    at = new_app().run()
    at.text_input(key="q").set_value("candes").run()
    assert f"**{text.count_text(1, 170)}**" in sidebar_markdown(at)


def test_each_filter_narrows_the_list(tree: TreeRecorder) -> None:
    at = new_app().run()
    at.multiselect(key="families").set_value(["Class Discovery"]).run()
    assert f"**{text.count_text(31, 170)}**" in sidebar_markdown(at)
    at.multiselect(key="families").set_value([]).run()
    at.multiselect(key="code_types").set_value(["No public code found"]).run()
    assert f"**{text.count_text(40, 170)}**" in sidebar_markdown(at)
    at.multiselect(key="code_types").set_value([]).run()
    at.multiselect(key="checks").set_value(["Incomplete or flagged"]).run()
    assert f"**{text.count_text(8, 170)}**" in sidebar_markdown(at)


def test_year_slider_narrows_the_list(tree: TreeRecorder) -> None:
    at = new_app().run()
    at.slider(key="years").set_range(2026, 2026).run()
    assert not at.exception
    assert f"**{text.count_text(10, 170)}**" in sidebar_markdown(at)  # ten from 2026
    leaves = [
        leaf
        for family in tree.last["data"]
        for section in family["children"]
        for leaf in section.get("children", [])
    ]
    assert leaves
    at.slider(key="years").set_range(1954, 1954).run()
    assert f"**{text.count_text(1, 170)}**" in sidebar_markdown(at)


def test_a_search_with_no_match_shows_a_message_instead_of_the_tree(
    tree: TreeRecorder,
) -> None:
    at = new_app().run()
    calls_before = len(tree.calls)
    at.text_input(key="q").set_value("zzzzqqqq").run()
    assert not at.exception
    assert len(tree.calls) == calls_before  # no empty tree is drawn
    assert [element.value for element in at.info] == [text.NO_MATCH]
    assert f"**{text.count_text(0, 170)}**" in sidebar_markdown(at)


def test_regex_characters_in_the_search_box_are_harmless(tree: TreeRecorder) -> None:
    at = new_app().run()
    for query in ("(", "[a-", ".*", "\\", "a|b", "(?i)"):
        at.text_input(key="q").set_value(query).run()
        assert not at.exception, query


def test_the_download_button_is_there_and_disabled_without_rows(
    tree: TreeRecorder,
) -> None:
    at = new_app().run()
    buttons = at.get("download_button")
    assert len(buttons) == 1
    assert not buttons[0].proto.disabled
    at.text_input(key="q").set_value("zzzzqqqq").run()
    assert at.get("download_button")[0].proto.disabled


# --- selection, the card and the address ----------------------------------------------


def test_a_deep_link_selects_the_method_and_opens_only_its_ancestors(
    tree: TreeRecorder,
) -> None:
    at = new_app()
    at.query_params["m"] = "4"
    at.run()
    assert not at.exception
    call = tree.last
    assert call["selection"] == "4"
    unknown = "Unknown Rejection"
    section_1_1 = "1.1 Discriminative Open Set Recognition"
    assert call["initial_open_state"] == {
        family_id(unknown): True,
        section_id(unknown, section_1_1): True,
        type_id(unknown, section_1_1, "Extreme-value calibrated"): True,
    }
    assert call["open_by_default"] is False
    assert card_text(at).count("### OpenMax") == 1
    assert at.session_state["selected_id"] == "4"
    assert at.query_params["m"] == "4"


def test_the_card_shows_the_reference_in_a_code_block_for_copying(
    tree: TreeRecorder, methods: Any
) -> None:
    at = new_app()
    at.query_params["m"] = "1"
    at.run()
    row = methods.loc[methods["id"] == "1"].iloc[0].to_dict()
    assert card_markdown(row) in main_markdown(at)
    assert [element.value for element in at.code] == [reference_text(row)]


@pytest.mark.parametrize(
    "bad",
    [
        "zzz",
        "n1",
        "",
        "4" * 500,
        "<script>alert(1)</script>",
        "family:Unknown Rejection",
    ],
)
def test_a_bad_deep_link_is_ignored_and_taken_out_of_the_address(
    tree: TreeRecorder, bad: str
) -> None:
    at = new_app()
    at.query_params["m"] = bad
    at.run()
    assert not at.exception
    assert tree.last["selection"] is None
    assert at.session_state["selected_id"] is None
    assert card_column_markdown(at) == [text.HOW_TO_READ]
    assert "m" not in at.query_params


def test_the_alphanumeric_id_of_an_added_method_works_as_a_deep_link(
    tree: TreeRecorder,
) -> None:
    at = new_app()
    at.query_params["m"] = "N1"
    at.run()
    assert tree.last["selection"] == "N1"
    assert "### AiGAS-OSR-dEVL" in card_text(at)


def test_a_method_without_authors_renders_without_an_author_line(
    tree: TreeRecorder,
) -> None:
    at = new_app()
    at.query_params["m"] = "18"
    at.run()
    card = selected_card(at)
    assert card.startswith("### ALSET")
    assert "et al." not in card
    assert "Authors" not in card


def test_the_address_follows_the_selection(tree: TreeRecorder) -> None:
    at = new_app()
    at.session_state["selected_id"] = "7"  # what the click callback does
    at.run()
    assert at.query_params["m"] == "7"
    assert selected_card(at).startswith("### Objectosphere")


class AddressSpy:
    """Records every write to ``st.query_params`` (and every removal)."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, str | None]] = []


@pytest.fixture
def address_spy(monkeypatch: pytest.MonkeyPatch) -> AddressSpy:
    from streamlit.runtime.state.query_params_proxy import QueryParamsProxy

    spy = AddressSpy()
    original_set, original_delete = (
        QueryParamsProxy.__setitem__,
        QueryParamsProxy.__delitem__,
    )

    def recording_set(self, key, value):  # type: ignore[no-untyped-def]
        spy.writes.append((key, value))
        return original_set(self, key, value)

    def recording_delete(self, key):  # type: ignore[no-untyped-def]
        spy.writes.append((key, None))
        return original_delete(self, key)

    monkeypatch.setattr(QueryParamsProxy, "__setitem__", recording_set)
    monkeypatch.setattr(QueryParamsProxy, "__delitem__", recording_delete)
    return spy


def test_the_address_is_sent_whenever_it_differs_from_what_was_last_sent(
    tree: TreeRecorder, address_spy: AddressSpy
) -> None:
    """Rapid clicks: the address the page shows when a rerun is requested can be older than
    a message from the run before it, so the app must not trust it to skip a write."""
    at = new_app()
    at.session_state["selected_id"] = "4"
    at.run()  # sends m=4
    at.query_params["m"] = "5"  # the (already out of date) address this request carries
    at.session_state["selected_id"] = "5"
    at.run()
    sent = [value for key, value in address_spy.writes if key == "m"]
    assert sent == ["4", "5"], "m=5 must be sent even though the request already said 5"


def test_nothing_is_sent_while_the_selection_is_unchanged(
    tree: TreeRecorder, address_spy: AddressSpy
) -> None:
    at = new_app()
    at.session_state["selected_id"] = "4"
    at.run()
    at.text_input(key="q").set_value("open").run()  # an unrelated rerun
    at.text_input(key="q").set_value("").run()
    assert [value for key, value in address_spy.writes if key == "m"] == ["4"]


def test_the_address_is_cleaned_once_when_the_selection_is_empty(
    tree: TreeRecorder, address_spy: AddressSpy
) -> None:
    at = new_app()
    at.query_params["m"] = "zzz"
    at.run()
    at.text_input(key="q").set_value("open").run()
    assert "m" not in at.query_params
    assert at.session_state["address_sent"] is None
    removals = [value for key, value in address_spy.writes if key == "m"]
    assert removals == [None]  # removed once, not again on the unrelated rerun


def test_props_stay_constant_while_the_key_is_unchanged(tree: TreeRecorder) -> None:
    at = new_app()
    at.query_params["m"] = "4"
    at.run()
    first = tree.last
    at.session_state["selected_id"] = "N4"  # a click on another method
    at.run()
    again = tree.last
    assert again["key"] == first["key"]
    assert (
        again["selection"] == first["selection"] == "4"
    )  # never re-pushed: no loop of reruns
    assert again["initial_open_state"] == first["initial_open_state"]
    assert "### Halász et al. (fake features)" in card_text(
        at
    )  # but the card follows the click


def test_a_click_from_a_replaced_tree_mounts_a_fresh_tree_with_that_selection(
    tree: TreeRecorder,
) -> None:
    """Type a search term and click a row of the old tree before the new one arrives:
    the click is remembered, and the tree that replaces it must show it."""
    at = new_app().run()
    first = tree.last
    assert first["selection"] is None
    at.session_state["selected_id"] = "4"  # what the callback stored
    at.session_state["tree_stale_click"] = True  # and what it noticed
    at.run()
    fresh = tree.last
    assert fresh["key"] != first["key"]
    assert fresh["selection"] == "4"
    assert family_id("Unknown Rejection") in fresh["initial_open_state"]
    assert "tree_stale_click" not in at.session_state  # consumed
    at.run()  # and from then on the props are constant again
    assert tree.last["key"] == fresh["key"]
    assert tree.last["selection"] == "4"


def test_the_widget_key_the_callback_compares_with_is_the_one_on_screen(
    tree: TreeRecorder,
) -> None:
    at = new_app().run()
    assert at.session_state["tree_widget_key"] == tree.last["key"]


def test_a_selection_hidden_by_a_filter_is_not_passed_to_the_tree_but_is_kept(
    tree: TreeRecorder,
) -> None:
    at = new_app()
    at.query_params["m"] = "4"
    at.run()
    at.text_input(key="q").set_value("halasz").run()
    assert tree.last["selection"] is None
    assert card_column_markdown(at) == [text.HOW_TO_READ]
    assert at.session_state["selected_id"] == "4"
    assert at.query_params["m"] == "4"
    at.text_input(key="q").set_value(
        ""
    ).run()  # filter cleared: the tree is mounted afresh
    assert tree.last["selection"] == "4"
    assert "### OpenMax" in card_text(at)


def test_a_selection_that_stays_visible_is_highlighted_after_a_filter_change(
    tree: TreeRecorder,
) -> None:
    at = new_app()
    at.query_params["m"] = "N3"
    at.run()
    at.text_input(key="q").set_value("halasz").run()
    assert tree.last["selection"] == "N3"
    assert family_id("Unknown Rejection") in tree.last["initial_open_state"]


def test_returning_from_an_empty_result_mounts_the_tree_afresh_with_the_current_selection(
    tree: TreeRecorder,
) -> None:
    at = new_app().run()
    assert tree.last["selection"] is None
    at.session_state["selected_id"] = "7"  # clicked while the tree was shown
    at.run()
    assert tree.last["selection"] is None  # same key: untouched
    at.text_input(key="q").set_value("zzzzqqqq").run()  # the tree disappears
    at.text_input(key="q").set_value("").run()  # and returns under the very same key
    assert tree.last["selection"] == "7"
    assert tree.last["initial_open_state"]


# --- when the data cannot be used -----------------------------------------------------


def test_unusable_data_shows_the_problem_and_stops(
    tree: TreeRecorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = write_csv(tmp_path / "bad.csv", make_row(id="X1", year="20x0"))
    monkeypatch.setattr("explorer.constants.DATA_PATH", bad)
    at = new_app().run()
    assert [element.value for element in at.error] == [text.DATA_ERROR]
    assert any("X1" in element.value and "year" in element.value for element in at.code)
    assert not tree.calls
    assert not at.title  # nothing else is drawn


def test_missing_data_file_shows_the_problem_and_stops(
    tree: TreeRecorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("explorer.constants.DATA_PATH", tmp_path / "absent.csv")
    at = new_app().run()
    assert [element.value for element in at.error] == [text.DATA_ERROR]
    assert not tree.calls


def test_the_shipped_csv_is_the_one_the_app_reads() -> None:
    from explorer.constants import DATA_PATH

    assert DATA_PATH == CSV_PATH == SITE_ROOT / "data" / "methods_public.csv"
    assert DATA_PATH.is_file()


# --- the data file can change while the server keeps running ---------------------------


def test_a_changed_data_file_is_picked_up_without_touching_any_code(
    tree: TreeRecorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacing data/methods_public.csv and pushing must show the new rows."""
    import os

    path = write_csv(tmp_path / "data.csv", make_row(id="1"), make_row(id="2"))
    monkeypatch.setattr("explorer.constants.DATA_PATH", path)
    at = new_app().run()
    assert f"**{text.count_text(2, 2)}**" in sidebar_markdown(at)

    write_csv(path, make_row(id="1"), make_row(id="2"), make_row(id="3"))
    stamp = path.stat().st_mtime_ns + 5_000_000_000
    os.utime(path, ns=(stamp, stamp))  # whatever the clock resolution of the disk
    at.run()
    assert f"**{text.count_text(3, 3)}**" in sidebar_markdown(at)


def test_a_long_pasted_search_is_kept(tree: TreeRecorder) -> None:
    at = new_app().run()
    pasted = (
        "Learning a Neural-Network-Based Representation for Open Set Recognition " * 2
    )
    assert 100 < len(pasted) <= 300
    at.text_input(key="q").set_value(pasted).run()
    assert at.text_input(key="q").value == pasted


def test_a_data_file_with_a_single_year_has_no_year_slider(
    tree: TreeRecorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_csv(
        tmp_path / "one_year.csv",
        make_row(id="1", year="2020"),
        make_row(id="2", year="2020"),
    )
    monkeypatch.setattr("explorer.constants.DATA_PATH", path)
    at = new_app().run()
    assert not at.exception
    assert len(at.slider) == 0
    assert f"**{text.count_text(2, 2)}**" in sidebar_markdown(at)
