"""Snapshot of the shipped data/abstracts.csv.

These numbers describe the file as delivered. After running ``python -m
tools.fetch_abstracts`` or adding abstracts by hand, update them here.
"""

from __future__ import annotations

import pandas as pd
import pytest

from explorer.abstracts import abstracts_path_for, load_abstracts, load_collection
from explorer.constants import ABSTRACT_FIELDS, DATA_PATH
from explorer.data import load_methods
from tools.abstract_file import read_abstracts
from tools.abstract_parsing import accept, title_similarity

pytestmark = pytest.mark.unit

# Methods whose abstracts no open source carries (publisher-restricted or not online).
# (Id 14 is here too: OpenAlex only has an abstract for a dataset of the same title.)
WITHOUT_ABSTRACT = {
    "3", "14", "17", "18", "20", "50", "112", "113", "119", "120", "121", "122",
    "123", "125", "130", "133", "134", "138", "142", "147", "148", "153", "156", "N1",
}  # fmt: skip

# Lines whose title differs too much from the method's for the title alone to accept them.
# Each was accepted by the tool because the arXiv id, a close title and the first author
# agree; the author is not in the file, so the check here cannot repeat that, and the line
# was checked by hand.
CHECKED_BY_HAND = {
    "54": "arXiv spells out 'GANs' as 'Generative Adversarial Networks'",
}


@pytest.fixture(scope="module")
def collection() -> pd.DataFrame:
    return load_collection(DATA_PATH)


def test_the_file_sits_next_to_the_methods_and_is_valid() -> None:
    path = abstracts_path_for(DATA_PATH)
    assert path.is_file()
    assert len(load_abstracts(path)) == 146


def test_counts_by_source() -> None:
    frame = load_abstracts(abstracts_path_for(DATA_PATH))
    assert frame["abstract_source"].value_counts().to_dict() == {
        "arXiv": 99,
        "OpenAlex": 41,
        "CVF": 5,
        "PMLR": 1,
    }


def test_exactly_the_known_methods_have_no_abstract(collection: pd.DataFrame) -> None:
    missing = set(collection.loc[collection["abstract"] == "", "id"])
    assert missing == WITHOUT_ABSTRACT
    assert len(collection) - len(missing) == 146


def test_every_abstract_is_a_real_paragraph_with_its_source(
    collection: pd.DataFrame,
) -> None:
    have = collection[collection["abstract"] != ""]
    assert (have["abstract"].str.len() >= 300).all()
    assert (have["abstract_url"].str.startswith("https://")).all()
    assert (have["abstract_source"] != "").all()
    assert not have["abstract"].duplicated().any()  # one text per paper


def test_the_collection_keeps_the_methods_in_file_order(
    collection: pd.DataFrame,
) -> None:
    assert collection["id"].tolist() == load_methods(DATA_PATH)["id"].tolist()


def test_methods_without_abstracts_have_empty_fields_not_missing_ones(
    collection: pd.DataFrame,
) -> None:
    empty = collection[collection["abstract"] == ""]
    for name in ABSTRACT_FIELDS:
        assert (empty[name] == "").all()


def test_every_line_agrees_with_the_title_its_own_source_gave() -> None:
    """The file records what the source called the paper; it must still be that paper."""
    lines = read_abstracts(abstracts_path_for(DATA_PATH))
    rows = {row["id"]: row for row in load_methods(DATA_PATH).to_dict(orient="records")}
    disagree = []
    for key, line in lines.items():
        assert line.title, f"id {key} has no source_title"
        if line.matched_by == "title":
            agrees = title_similarity(rows[key]["title"], line.title) >= 0.93
        else:
            agrees = accept(rows[key], line)
        if not agrees:
            disagree.append(key)
    assert set(disagree) == set(CHECKED_BY_HAND)  # nothing else, and nothing stale here
