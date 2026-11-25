"""The Streamlit configuration file that ships with the site."""

from __future__ import annotations

import json
import tomllib

import pandas as pd
import pytest

from explorer.constants import SITE_ROOT
from explorer.tree import build_tree

pytestmark = pytest.mark.unit

CONFIG = SITE_ROOT / ".streamlit" / "config.toml"


def load_config() -> dict:
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))


def test_the_theme_is_fixed_to_light() -> None:
    assert load_config()["theme"]["base"] == "light"


def test_messages_the_size_of_the_tree_are_never_replaced_by_a_hash(
    methods: pd.DataFrame,
) -> None:
    """A repeated message above this size is sent as a hash, and the browser can miss it."""
    limit = load_config()["global"]["minCachedMessageSize"]
    assert limit > len(json.dumps(build_tree(methods)))
