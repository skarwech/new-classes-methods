"""A browsable tree of methods with a detail card.

Run it from this folder with ``streamlit run app.py``. The logic lives in the
``explorer`` package; this file only lays out the page and wires the pieces together.
"""

from __future__ import annotations

import functools
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_arborist import tree_view

from explorer import text
from explorer.card import card_markdown, reference_text
from explorer.constants import (
    CHECK_FILTER_LABELS,
    CHECK_VALUES,
    CODE_LABELS,
    CODE_TYPES,
    DATA_PATH,
    LAYOUT_RATIO,
    MAX_QUERY_CHARS,
    SELECTED_PARAM,
    TREE_HEIGHT,
    TREE_INDENT,
    TREE_ROW_HEIGHT,
)
from explorer.data import DataError, load_methods
from explorer.export import csv_bytes
from explorer.filters import Filters, apply_filters, year_bounds
from explorer.selection import remember_click, resolve_selection
from explorer.tree import Node, build_tree, leaf_ids, plan_mount, tree_key

STATE_SELECTED = "selected_id"  # the method shown on the card
STATE_MOUNT = "tree_mount"  # what the tree was last mounted with
STATE_WIDGET = "tree_widget_key"  # key of the tree widget that is on screen
STATE_STALE = "tree_stale_click"  # a click came from a tree that was replaced
STATE_ADDRESS = "address_sent"  # the id last written to ?m= (None: removed)
_NOT_SENT = object()

st.set_page_config(page_title=text.TITLE, layout="wide")


def file_version(path: Path) -> int:
    """When the file last changed, so that a replaced CSV is read again."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0  # the loader reports the problem


@st.cache_data(show_spinner=False)
def get_methods(path: str, version: int) -> pd.DataFrame:
    """Read and validate the CSV; read it again when ``version`` changes."""
    return load_methods(path)


def render_header(total: int) -> None:
    st.title(text.TITLE, anchor=False)
    st.markdown(text.description(total))
    with st.expander(text.HOW_TO_READ_LABEL):
        st.markdown(text.HOW_TO_READ)


def render_filters(methods: pd.DataFrame) -> Filters:
    """Draw the search box and filters in the sidebar and return what was chosen."""
    low, high = year_bounds(methods)
    with st.sidebar:
        st.header(text.SIDEBAR_HEADER, anchor=False)
        query = st.text_input(text.SEARCH_LABEL, key="q", max_chars=MAX_QUERY_CHARS)
        st.caption(text.SEARCH_HINT)
        families = st.multiselect(
            text.FAMILY_LABEL,
            options=list(dict.fromkeys(methods["tree_family"])),
            key="families",
        )
        code_types = st.multiselect(
            text.CODE_FILTER_LABEL,
            options=list(CODE_TYPES),
            format_func=CODE_LABELS.__getitem__,
            key="code_types",
        )
        checks = st.multiselect(
            text.CHECK_FILTER_LABEL,
            options=list(CHECK_VALUES),
            format_func=CHECK_FILTER_LABELS.__getitem__,
            key="checks",
        )
        years = (
            st.slider(
                text.YEAR_LABEL,
                min_value=low,
                max_value=high,
                value=(low, high),
                key="years",
            )
            if low < high
            else None
        )
    return Filters.from_inputs(
        query=query,
        families=families,
        code_types=code_types,
        checks=checks,
        year_range=years,
        year_bounds=(low, high),
    )


def render_sidebar_footer(filtered: pd.DataFrame, total: int) -> None:
    """The "N of 170 methods" counter and the CSV download of the filtered rows."""
    with st.sidebar:
        st.markdown(f"**{text.count_text(len(filtered), total)}**")
        st.download_button(
            text.DOWNLOAD_LABEL,
            data=csv_bytes(filtered),
            file_name=text.DOWNLOAD_FILE_NAME,
            mime="text/csv",
            on_click="ignore",
            disabled=filtered.empty,
            key="download",
        )


def render_tree(
    nodes: list[Node], filters: Filters, selected: str | None, known: frozenset[str]
) -> None:
    """Draw the tree: props fixed per mount (see ``plan_mount``), clicks by callback."""
    mount = plan_mount(
        st.session_state.get(STATE_MOUNT),
        key=tree_key(filters),
        nodes=nodes,
        filters_active=filters.is_active(),
        selected=selected,
        stale=st.session_state.pop(STATE_STALE, False),
    )
    st.session_state[STATE_MOUNT] = mount
    st.session_state[STATE_WIDGET] = mount.widget_key
    tree_view(
        nodes,
        row_height=TREE_ROW_HEIGHT,
        height=TREE_HEIGHT,
        indent=TREE_INDENT,
        open_by_default=False,
        selection=mount.selection,
        initial_open_state=dict.fromkeys(mount.open_ids, True) or None,
        key=mount.widget_key,
        on_change=functools.partial(
            remember_click,
            st.session_state,
            mount.widget_key,
            known,
            STATE_SELECTED,
            current_widget_key=STATE_WIDGET,
            stale_key=STATE_STALE,
        ),
    )


def render_card(methods: pd.DataFrame, selected: str | None) -> None:
    """The detail card; with nothing selected it shows how to read the page."""
    if selected is None:
        st.markdown(text.HOW_TO_READ)
        return
    row = methods.loc[methods["id"] == selected].iloc[0].to_dict()
    st.markdown(card_markdown(row), anchors=False)
    st.code(reference_text(row), language=None, wrap_lines=True)


def sync_address(selected: str | None) -> None:
    """Keep ``?m=<id>`` equal to the selection; other address parameters are left alone.

    What was last *sent* is remembered here instead of being read back from
    ``st.query_params``: that is the browser's address as it was when this rerun was
    requested, which can be older than a message from the run before it. Trusting it
    could skip a write and leave the address behind the selection after quick clicks.
    """
    if st.session_state.get(STATE_ADDRESS, _NOT_SENT) == selected:
        return
    if selected is None:
        st.query_params.pop(SELECTED_PARAM, None)
    else:
        st.query_params[SELECTED_PARAM] = selected
    st.session_state[STATE_ADDRESS] = selected


def main() -> None:
    try:
        methods = get_methods(str(DATA_PATH), file_version(DATA_PATH))
    except DataError as error:
        st.error(text.DATA_ERROR)
        st.code(str(error), language=None)
        st.stop()

    render_header(len(methods))
    filters = render_filters(methods)
    filtered = apply_filters(methods, filters)
    render_sidebar_footer(filtered, len(methods))

    known = frozenset(methods["id"])
    selected = resolve_selection(
        current=st.session_state.get(STATE_SELECTED),
        url=st.query_params.get(SELECTED_PARAM),
        known=known,
    )
    st.session_state[STATE_SELECTED] = selected

    nodes = build_tree(filtered)
    visible = frozenset(leaf_ids(nodes))
    tree_column, card_column = st.columns(LAYOUT_RATIO)
    with tree_column:
        if nodes:
            render_tree(nodes, filters, selected, known)
        else:
            st.session_state.pop(STATE_MOUNT, None)  # the next tree is a new mount
            st.session_state.pop(STATE_WIDGET, None)
            st.info(text.NO_MATCH)
    with card_column:
        render_card(methods, selected if selected in visible else None)
    sync_address(selected)


main()
