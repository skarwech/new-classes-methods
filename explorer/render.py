"""Draws one method: the card, the abstract with its source, and the reference.

The app and the test page that shows every card use these functions, so the page that
is checked is the page that is shipped.
"""

from __future__ import annotations

import streamlit as st

from .card import (
    REFERENCE_LABEL,
    Row,
    abstract_heading,
    abstract_html,
    abstract_source_markdown,
    card_markdown,
    reference_text,
)


def render_abstract(row: Row) -> None:
    """The abstract as escaped text with its source, or a note saying none."""
    st.markdown(abstract_heading(row))
    paragraph = abstract_html(row)
    if paragraph:
        st.html(paragraph)
        st.markdown(abstract_source_markdown(row))


def render_method(row: Row) -> None:
    """The details, the abstract, and the reference ready to copy."""
    st.markdown(card_markdown(row), anchors=False)
    render_abstract(row)
    st.markdown(REFERENCE_LABEL)
    st.code(reference_text(row), language=None, wrap_lines=True)
