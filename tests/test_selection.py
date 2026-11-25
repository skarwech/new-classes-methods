"""Which method is selected: one pure function over the three places that can say so."""

from __future__ import annotations

import pytest

from explorer.constants import MAX_ID_LENGTH
from explorer.selection import clicked_id, remember_click, resolve_selection, valid_id

pytestmark = pytest.mark.unit

KNOWN = frozenset({"4", "5", "7", "18", "N1"})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("4", "4"),
        (" 4 ", "4"),
        ("N1", "N1"),
        ("n1", None),  # ids are case-sensitive
        ("6", None),  # not a known method
        ("", None),
        ("   ", None),
        ("4" * (MAX_ID_LENGTH + 1), None),
        ("<script>alert(1)</script>", None),
        ("4; DROP TABLE methods", None),
        ("family:Unknown Rejection", None),
        (None, None),
        (4, None),
        (["4"], None),
        (b"4", None),
    ],
)
def test_valid_id(raw: object, expected: str | None) -> None:
    assert valid_id(raw, KNOWN) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"id": "4", "name": "OpenMax (2016)"}, "4"),
        ({"id": "N1"}, "N1"),
        (
            {
                "id": "family:Unknown Rejection",
                "name": "Unknown Rejection (63)",
                "children": [],
            },
            None,
        ),
        ({"id": "6"}, None),
        ({"id": 4}, None),
        ({"name": "no id"}, None),
        ({}, None),
        ("4", None),
        (["4"], None),
        (None, None),
    ],
)
def test_clicked_id_reads_the_node_the_component_returns(
    value: object, expected: str | None
) -> None:
    assert clicked_id(value, KNOWN) == expected


# The case table: what is selected, given what the session remembers and what the address says.
@pytest.mark.parametrize(
    ("current", "url", "expected"),
    [
        # nothing anywhere
        (None, None, None),
        # first visit through a deep link
        (None, "4", "4"),
        (None, " 4 ", "4"),
        (None, "N1", "N1"),
        # a bad deep link is ignored
        (None, "zzz", None),
        (None, "n1", None),
        (None, "", None),
        (None, "   ", None),
        (None, "4" * 1000, None),
        (None, "<script>alert(1)</script>", None),
        (None, ["4"], None),
        (None, 4, None),
        # the session wins once it has a selection: the address only mirrors it
        ("7", "4", "7"),
        ("7", None, "7"),
        ("7", "zzz", "7"),
        # a remembered id that is no longer valid falls back to the address
        ("zzz", "4", "4"),
        ("zzz", None, None),
    ],
)
def test_resolve_selection_case_table(
    current: str | None, url: object, expected: str | None
) -> None:
    assert resolve_selection(current=current, url=url, known=KNOWN) == expected


# The click callback: the one place where a click turns into the remembered selection.
WIDGET_KEY = "tree-abc"
SELECTED_KEY = "selected_id"


def test_remember_click_stores_a_clicked_method() -> None:
    state: dict = {WIDGET_KEY: {"id": "5", "name": "EVM (2018)"}}
    remember_click(state, WIDGET_KEY, KNOWN, SELECTED_KEY)
    assert state[SELECTED_KEY] == "5"


@pytest.mark.parametrize(
    "value",
    [
        {"id": "family:Unknown Rejection", "name": "x", "children": []},  # a folder
        {"id": "zzz"},  # unknown
        {"id": 5},  # wrong type
        "junk",
        None,
    ],
)
def test_remember_click_ignores_everything_that_is_not_a_known_method(
    value: object,
) -> None:
    state: dict = {WIDGET_KEY: value, SELECTED_KEY: "7"}
    remember_click(state, WIDGET_KEY, KNOWN, SELECTED_KEY)
    assert state[SELECTED_KEY] == "7"  # the earlier selection survives


def test_remember_click_with_no_widget_value_changes_nothing() -> None:
    state: dict = {}
    remember_click(state, WIDGET_KEY, KNOWN, SELECTED_KEY)
    assert state == {}


def test_remember_click_touches_only_the_selection_key() -> None:
    state: dict = {WIDGET_KEY: {"id": "4"}, "other": 1}
    remember_click(state, WIDGET_KEY, KNOWN, SELECTED_KEY)
    assert state == {WIDGET_KEY: {"id": "4"}, "other": 1, SELECTED_KEY: "4"}


# A click from a tree that is no longer the mounted one.
CURRENT = "current_widget"
STALE = "stale_click"


def _stale_state(**extra: object) -> dict:
    return {CURRENT: "tree-new", "tree-old": {"id": "5"}, **extra}


def test_a_click_from_the_mounted_tree_is_not_stale() -> None:
    state = {CURRENT: "tree-new", "tree-new": {"id": "5"}}
    remember_click(
        state,
        "tree-new",
        KNOWN,
        SELECTED_KEY,
        current_widget_key=CURRENT,
        stale_key=STALE,
    )
    assert state[SELECTED_KEY] == "5"
    assert STALE not in state


def test_a_click_from_a_replaced_tree_is_remembered_and_flagged() -> None:
    state = _stale_state()
    remember_click(
        state,
        "tree-old",
        KNOWN,
        SELECTED_KEY,
        current_widget_key=CURRENT,
        stale_key=STALE,
    )
    assert state[SELECTED_KEY] == "5"
    assert state[STALE] is True


def test_a_stale_value_that_is_not_a_method_flags_nothing() -> None:
    state = {CURRENT: "tree-new", "tree-old": {"id": "family:x"}}
    remember_click(
        state,
        "tree-old",
        KNOWN,
        SELECTED_KEY,
        current_widget_key=CURRENT,
        stale_key=STALE,
    )
    assert SELECTED_KEY not in state
    assert STALE not in state


def test_without_the_stale_keys_nothing_is_flagged() -> None:
    state = _stale_state()
    remember_click(state, "tree-old", KNOWN, SELECTED_KEY)
    assert state[SELECTED_KEY] == "5"
    assert STALE not in state
