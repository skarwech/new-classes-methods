"""Runs the real ``app.py`` and shows how many times the script has run.

The count lets the browser tests tell "a click settled" from "the page keeps rerunning".
This file is only used by the tests; the application itself has no test code in it.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import streamlit as st

SITE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SITE_ROOT))

st.session_state["script_runs"] = st.session_state.get("script_runs", 0) + 1
runpy.run_path(str(SITE_ROOT / "app.py"), run_name="__main__")
st.sidebar.caption(f"script runs: {st.session_state['script_runs']}")
