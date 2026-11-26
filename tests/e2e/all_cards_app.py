"""Shows the card of every method on one page, to check how each one renders.

Only the tests use this page. It draws each card with the same function as the app.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

SITE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SITE_ROOT))

from explorer.abstracts import load_collection  # noqa: E402
from explorer.constants import DATA_PATH  # noqa: E402
from explorer.render import render_method  # noqa: E402

st.set_page_config(layout="wide")
for row in load_collection(DATA_PATH).to_dict(orient="records"):
    with st.container(key=f"card-{row['id']}"):
        render_method(row)
