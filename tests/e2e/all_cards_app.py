"""Shows the card of every method on one page, to check how each one renders.

Only the tests use this page. It builds the cards with the same functions as the app.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

SITE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SITE_ROOT))

from explorer.card import card_markdown, reference_text  # noqa: E402
from explorer.constants import DATA_PATH  # noqa: E402
from explorer.data import load_methods  # noqa: E402

st.set_page_config(layout="wide")
for row in load_methods(DATA_PATH).to_dict(orient="records"):
    with st.container(key=f"card-{row['id']}"):
        st.markdown(card_markdown(row), anchors=False)
        st.code(reference_text(row), language=None, wrap_lines=True)
