"""Building the tree: labels, order, counts, ancestors, and the mount plan."""

from __future__ import annotations

import itertools
from collections.abc import Iterator, Mapping

import pandas as pd
import pytest

from explorer.constants import CHECK_VALUES, CODE_TYPES
from explorer.filters import Filters, apply_filters
from explorer.tree import (
    TreeMount,
    ancestor_ids,
    build_tree,
    count_leaves,
    family_id,
    folder_ids,
    folders_to_open,
    is_folder,
    leaf_ids,
    leaf_label,
    plan_mount,
    section_id,
    tree_key,
    type_id,
)
from tests.conftest import make_frame, make_row

pytestmark = pytest.mark.unit

# The expected top two levels of the unfiltered tree, labels and counts included.
EXPECTED_TREE = """\
Unknown Rejection (63)
  1.1 Discriminative Open Set Recognition (19)
  1.2 Generative Open Set Recognition (9)
  1.3 Out-of-Distribution Detection (22)
  1.4 One-Class Novelty / Anomaly Detection (13)
Class Discovery (31)
  2.1 Novel Class Discovery (9)
  2.2 Generalized Category Discovery (13)
  2.3 Continual and Online Category Discovery (9)
Model Integration (23)
  3.1 Open World Recognition (5)
  3.2 Class-Incremental Learning (18)
Stream Adaptation (43)
  4.1 Emerging Class Detection (9)
  4.2 Concept Drift Detection and Adaptation (14)
  4.3 Extreme Verification Latency (5)
  4.4 Streaming Open-Set Methods, 2021–2026 (10)
  4.5 Industrial Process Fault Diagnosis (5)
Pipeline component references (10)
  Statistical building blocks (4)
  Class-count estimation and stream evaluation (6)
"""


def walk(nodes: list[dict], depth: int = 0) -> Iterator[tuple[int, dict]]:
    for node in nodes:
        yield depth, node
        yield from walk(node.get("children", []), depth + 1)


def top_two_levels(nodes: list[dict]) -> str:
    lines = []
    for family in nodes:
        lines.append(family["name"])
        lines.extend(f"  {section['name']}" for section in family["children"])
    return "\n".join(lines) + "\n"


def assert_tree_is_consistent(nodes: list[dict], frame: pd.DataFrame) -> None:
    """The invariants that must hold for the tree of any filtered frame."""
    all_ids = [node["id"] for _, node in walk(nodes)]
    assert len(all_ids) == len(set(all_ids)), "node ids must be unique"
    assert sorted(leaf_ids(nodes)) == sorted(
        frame["id"]
    ), "leaves must equal the filtered rows"
    for _, node in walk(nodes):
        if is_folder(node):
            assert node["children"], f"empty folder: {node['name']}"
            assert node["name"].endswith(f"({count_leaves(node)})"), node["name"]
            assert count_leaves(node) == sum(
                count_leaves(child) for child in node["children"]
            )
        else:
            assert "children" not in node


# --- labels ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "year", "label"),
    [
        ("OpenMax", "2016", "OpenMax (2016)"),
        ("1-vs-Set", "2013", "1-vs-Set (2013)"),
        ("Ledoit & Wolf (2004)", "2004", "Ledoit & Wolf (2004)"),
        ("Xu & Xu (2023)", "2023", "Xu & Xu (2023)"),
        ("Gibbs & Candès (2021)", "2021", "Gibbs & Candès (2021)"),
        ("Ngnie (2026)", "2026", "Ngnie (2026)"),
        ("Arunthavanathan et al. (2020)", "2020", "Arunthavanathan et al. (2020)"),
        (
            "Umsonst, Ruths, Sandberg (2021/22)",
            "2021",
            "Umsonst, Ruths, Sandberg (2021/22)",
        ),
        ("Halász et al. (time series)", "2023", "Halász et al. (time series) (2023)"),
        (
            "Schaeffer et al. (dynamical CRP)",
            "2022",
            "Schaeffer et al. (dynamical CRP) (2022)",
        ),
    ],
)
def test_leaf_label_never_repeats_a_year_the_name_already_carries(
    method: str, year: str, label: str
) -> None:
    assert leaf_label(method, year) == label


def test_no_leaf_in_the_real_tree_shows_two_years(methods: pd.DataFrame) -> None:
    for _, node in walk(build_tree(methods)):
        if not is_folder(node):
            assert node["name"].count("(20") + node["name"].count("(19") <= 1, node[
                "name"
            ]


# --- the real tree --------------------------------------------------------------------


def test_unfiltered_tree_matches_the_expected_labels_and_counts(
    methods: pd.DataFrame,
) -> None:
    assert top_two_levels(build_tree(methods)) == EXPECTED_TREE


def test_leaves_follow_the_file_order(methods: pd.DataFrame) -> None:
    assert leaf_ids(build_tree(methods)) == methods["id"].tolist()


def test_unfiltered_tree_is_consistent(methods: pd.DataFrame) -> None:
    nodes = build_tree(methods)
    assert_tree_is_consistent(nodes, methods)
    assert len(leaf_ids(nodes)) == 170


def test_leaf_nodes_carry_the_csv_id_and_label(methods: pd.DataFrame) -> None:
    leaves = {
        node["id"]: node["name"]
        for _, node in walk(build_tree(methods))
        if not is_folder(node)
    }
    assert leaves["4"] == "OpenMax (2016)"
    assert leaves["N1"].startswith("AiGAS-OSR-dEVL")


def test_eight_numbered_sections_have_a_type_level(methods: pd.DataFrame) -> None:
    typed = []
    for family in build_tree(methods):
        for section in family["children"]:
            has_type = any(is_folder(child) for child in section["children"])
            if has_type and section["name"][0].isdigit():
                typed.append(section["name"].split()[0])
    assert typed == ["1.1", "1.2", "1.3", "1.4", "2.1", "3.2", "4.1", "4.2"]


def test_section_1_1_type_folders(methods: pd.DataFrame) -> None:
    section = build_tree(methods)[0]["children"][0]
    assert [child["name"] for child in section["children"]] == [
        "Margin-based (3)",
        "Extreme-value calibrated (2)",
        "Prototype- and representation-based (7)",
        "Logit-based / calibrated baselines (1)",
        "Domain variants (3)",
        "Time-series-specific (3)",
    ]


def test_a_section_can_hold_types_and_a_loose_method(methods: pd.DataFrame) -> None:
    section = build_tree(methods)[0]["children"][
        1
    ]  # 1.2 Generative Open Set Recognition
    kinds = [
        ("folder" if is_folder(child) else "leaf", child["name"])
        for child in section["children"]
    ]
    assert kinds == [
        ("folder", "Adversarial generation of unknowns (3)"),
        ("folder", "Reconstruction- and density-based (5)"),
        ("leaf", "Halász et al. (fake features) (2023)"),
    ]


def test_sections_without_types_list_methods_directly(methods: pd.DataFrame) -> None:
    section = build_tree(methods)[1]["children"][
        1
    ]  # 2.2 Generalized Category Discovery
    assert len(section["children"]) == 13
    assert not any(is_folder(child) for child in section["children"])


def test_build_tree_does_not_mutate_the_frame_and_returns_fresh_data(
    methods: pd.DataFrame,
) -> None:
    before = methods.copy(deep=True)
    first, second = build_tree(methods), build_tree(methods)
    assert methods.equals(before)
    assert first == second
    assert first is not second
    assert first[0] is not second[0]


def test_empty_frame_gives_an_empty_tree(methods: pd.DataFrame) -> None:
    assert build_tree(methods.iloc[0:0]) == []


# --- order and grouping on synthetic data ---------------------------------------------


def test_groups_by_first_appearance_not_by_adjacency_or_alphabet() -> None:
    frame = make_frame(
        make_row(id="r1", tree_family="B family", tree_section="S-b"),
        make_row(id="r2", tree_family="A family", tree_section="S-z"),
        make_row(id="r3", tree_family="B family", tree_section="S-a"),
        make_row(id="r4", tree_family="A family", tree_section="S-z"),
        make_row(id="r5", tree_family="B family", tree_section="S-b"),
    )
    nodes = build_tree(frame)
    assert [family["name"] for family in nodes] == ["B family (3)", "A family (2)"]
    assert [section["name"] for section in nodes[0]["children"]] == [
        "S-b (2)",
        "S-a (1)",
    ]
    assert leaf_ids(nodes) == ["r1", "r5", "r3", "r2", "r4"]


def test_types_and_loose_methods_keep_their_first_appearance_order() -> None:
    frame = make_frame(
        make_row(id="a", tree_type="T1"),
        make_row(id="b", tree_type=""),
        make_row(id="c", tree_type="T2"),
        make_row(id="d", tree_type="T1"),
    )
    section = build_tree(frame)[0]["children"][0]
    assert [child["name"].split(" (")[0] for child in section["children"]] == [
        "T1",
        "Method",
        "T2",
    ]
    assert leaf_ids([section]) == ["a", "d", "b", "c"]


def test_same_type_name_in_two_sections_gets_distinct_ids() -> None:
    frame = make_frame(
        make_row(id="a", tree_section="S1", tree_type="Same"),
        make_row(id="b", tree_section="S2", tree_type="Same"),
    )
    nodes = build_tree(frame)
    ids = [node["id"] for _, node in walk(nodes)]
    assert len(ids) == len(set(ids))


def test_folder_ids_cannot_collide_with_method_ids() -> None:
    frame = make_frame(
        make_row(
            id="Unknown Rejection", tree_family="Unknown Rejection", tree_section="1.1"
        )
    )
    nodes = build_tree(frame)
    ids = [node["id"] for _, node in walk(nodes)]
    assert len(ids) == len(set(ids))


# --- invariants under every filter ----------------------------------------------------

SINGLE_FILTERS = (
    [
        Filters(families=(family,))
        for family in (
            "Unknown Rejection",
            "Class Discovery",
            "Model Integration",
            "Stream Adaptation",
            "Pipeline component references",
        )
    ]
    + [Filters(code_types=(kind,)) for kind in CODE_TYPES]
    + [Filters(checks=(value,)) for value in CHECK_VALUES]
    + [
        Filters(query=query)
        for query in (
            "halasz",
            "candes",
            "open",
            "stream",
            "a",
            "e",
            "2",
            "(",
            "-",
            "et al",
            "zzzzqqqq",
        )
    ]
    + [
        Filters(year_range=span)
        for span in (
            (1954, 1999),
            (2000, 2009),
            (2010, 2019),
            (2020, 2026),
            (2016, 2016),
            (1954, 1954),
        )
    ]
)


@pytest.mark.parametrize("filters", SINGLE_FILTERS, ids=lambda f: f.signature())
def test_every_single_filter_yields_a_consistent_tree(
    methods: pd.DataFrame, filters: Filters
) -> None:
    filtered = apply_filters(methods, filters)
    nodes = build_tree(filtered)
    assert_tree_is_consistent(nodes, filtered)
    if filtered.empty:
        assert nodes == []


def test_family_code_and_check_combinations_yield_consistent_trees(
    methods: pd.DataFrame,
) -> None:
    families = methods["tree_family"].unique().tolist()
    for family, code, check in itertools.product(families, CODE_TYPES, CHECK_VALUES):
        filtered = apply_filters(
            methods, Filters(families=(family,), code_types=(code,), checks=(check,))
        )
        assert_tree_is_consistent(build_tree(filtered), filtered)


def test_counts_in_the_filtered_tree_follow_the_filter(methods: pd.DataFrame) -> None:
    nodes = build_tree(apply_filters(methods, Filters(query="halasz")))
    assert [family["name"] for family in nodes] == ["Unknown Rejection (2)"]
    assert [section["name"] for section in nodes[0]["children"]] == [
        "1.1 Discriminative Open Set Recognition (1)",
        "1.2 Generative Open Set Recognition (1)",
    ]


# --- helpers over the tree ------------------------------------------------------------


def test_folder_ids_are_qualified_by_their_whole_path(methods: pd.DataFrame) -> None:
    nodes = build_tree(methods)
    family = "Unknown Rejection"
    section = "1.1 Discriminative Open Set Recognition"
    assert nodes[0]["id"] == family_id(family)
    assert nodes[0]["children"][0]["id"] == section_id(family, section)
    assert nodes[0]["children"][0]["children"][0]["id"] == type_id(
        family, section, "Margin-based"
    )


def test_the_same_section_or_type_name_under_two_parents_gets_distinct_ids() -> None:
    frame = make_frame(
        make_row(id="a", tree_family="F1", tree_section="S", tree_type="T"),
        make_row(id="b", tree_family="F2", tree_section="S", tree_type="T"),
    )
    ids = folder_ids(build_tree(frame))
    assert len(ids) == 6
    assert len(set(ids)) == 6


def test_names_that_contain_a_separator_cannot_collide() -> None:
    frame = make_frame(
        make_row(id="x", tree_section="a|b", tree_type="c"),
        make_row(id="y", tree_section="a", tree_type="b|c"),
    )
    ids = folder_ids(build_tree(frame))
    assert len(ids) == len(set(ids))


def test_ancestors_of_a_typed_method(methods: pd.DataFrame) -> None:
    family = "Unknown Rejection"
    section = "1.1 Discriminative Open Set Recognition"
    assert ancestor_ids(build_tree(methods), "4") == [
        family_id(family),
        section_id(family, section),
        type_id(family, section, "Extreme-value calibrated"),
    ]


def test_ancestors_of_loose_methods_have_no_type(methods: pd.DataFrame) -> None:
    nodes = build_tree(methods)
    assert ancestor_ids(nodes, "N4") == [
        family_id("Unknown Rejection"),
        section_id("Unknown Rejection", "1.2 Generative Open Set Recognition"),
    ]
    first_in_2_2 = methods.loc[
        methods["tree_section"].str.startswith("2.2"), "id"
    ].iloc[0]
    assert len(ancestor_ids(nodes, first_in_2_2)) == 2


@pytest.mark.parametrize("missing", ["", "nope", "family:Unknown Rejection"])
def test_ancestors_of_unknown_or_folder_ids_are_empty(
    methods: pd.DataFrame, missing: str
) -> None:
    assert ancestor_ids(build_tree(methods), missing) == []


def test_folder_ids_and_leaf_ids_partition_all_nodes(methods: pd.DataFrame) -> None:
    nodes = build_tree(methods)
    folders, leaves = folder_ids(nodes), leaf_ids(nodes)
    assert len(folders) + len(leaves) == sum(1 for _ in walk(nodes))
    assert not set(folders) & set(leaves)
    assert len(folders) == len(set(folders))


# --- what to open at mount ------------------------------------------------------------


def test_nothing_opens_without_filters_or_selection(methods: pd.DataFrame) -> None:
    assert (
        folders_to_open(build_tree(methods), filters_active=False, selected=None) == ()
    )


def test_a_selection_opens_exactly_its_ancestors(methods: pd.DataFrame) -> None:
    nodes = build_tree(methods)
    assert folders_to_open(nodes, filters_active=False, selected="4") == tuple(
        ancestor_ids(nodes, "4")
    )


def test_an_unknown_selection_opens_nothing(methods: pd.DataFrame) -> None:
    assert (
        folders_to_open(build_tree(methods), filters_active=False, selected="nope")
        == ()
    )


def test_active_filters_open_every_folder(methods: pd.DataFrame) -> None:
    nodes = build_tree(apply_filters(methods, Filters(query="halasz")))
    assert set(folders_to_open(nodes, filters_active=True, selected=None)) == set(
        folder_ids(nodes)
    )
    assert set(folders_to_open(nodes, filters_active=True, selected="N3")) == set(
        folder_ids(nodes)
    )


# --- the key and the mount plan -------------------------------------------------------


def test_tree_key_depends_only_on_the_filters() -> None:
    a, b = Filters(query="halasz"), Filters(query="Halász")
    assert tree_key(a) == tree_key(b)
    assert tree_key(Filters()) != tree_key(a)
    assert tree_key(Filters()).startswith("tree-")
    assert tree_key(Filters(families=("Class Discovery",))) != tree_key(
        Filters(code_types=("none",))
    )


def test_first_mount_selects_a_visible_method_and_opens_its_ancestors(
    methods: pd.DataFrame,
) -> None:
    nodes = build_tree(methods)
    mount = plan_mount(None, key="k1", nodes=nodes, filters_active=False, selected="4")
    assert mount == TreeMount(
        key="k1", selection="4", open_ids=tuple(ancestor_ids(nodes, "4"))
    )


def test_a_hidden_selection_is_not_passed_to_the_tree(methods: pd.DataFrame) -> None:
    nodes = build_tree(apply_filters(methods, Filters(query="halasz")))
    mount = plan_mount(None, key="k2", nodes=nodes, filters_active=True, selected="4")
    assert mount.selection is None
    assert set(mount.open_ids) == set(folder_ids(nodes))


def test_the_same_key_keeps_the_props_the_tree_was_mounted_with(
    methods: pd.DataFrame,
) -> None:
    nodes = build_tree(methods)
    first = plan_mount(None, key="k1", nodes=nodes, filters_active=False, selected="4")
    again = plan_mount(
        first, key="k1", nodes=nodes, filters_active=False, selected="N4"
    )
    assert again is first  # a click must never change what the tree is told


def test_a_new_key_plans_a_fresh_mount(methods: pd.DataFrame) -> None:
    nodes = build_tree(methods)
    first = plan_mount(None, key="k1", nodes=nodes, filters_active=False, selected="4")
    second = plan_mount(
        first, key="k2", nodes=nodes, filters_active=False, selected="N4"
    )
    assert second is not first
    assert second.key == "k2"
    assert second.selection == "N4"


def test_returning_to_an_earlier_key_still_plans_a_fresh_mount(
    methods: pd.DataFrame,
) -> None:
    nodes = build_tree(methods)
    k1 = plan_mount(None, key="k1", nodes=nodes, filters_active=False, selected="4")
    k2 = plan_mount(k1, key="k2", nodes=nodes, filters_active=False, selected="4")
    k1_again = plan_mount(
        k2, key="k1", nodes=nodes, filters_active=False, selected="N4"
    )
    assert k1_again.selection == "N4"


def test_tree_mount_is_immutable() -> None:
    mount = TreeMount(key="k", selection=None, open_ids=())
    with pytest.raises(AttributeError):
        mount.key = "other"  # type: ignore[misc]


def test_is_folder_reads_the_children_key() -> None:
    node: Mapping[str, object] = {
        "id": "x",
        "name": "x",
        "children": [{"id": "y", "name": "y"}],
    }
    assert is_folder(node)
    assert not is_folder({"id": "y", "name": "y"})


# --- a click that arrives from a tree that has since been replaced ---------------------


def test_widget_key_is_the_filter_key_until_a_stale_click(
    methods: pd.DataFrame,
) -> None:
    nodes = build_tree(methods)
    first = plan_mount(None, key="k1", nodes=nodes, filters_active=False, selected=None)
    assert first.generation == 0
    assert first.widget_key == "k1"


def test_a_stale_click_forces_a_fresh_mount_under_a_new_widget_key(
    methods: pd.DataFrame,
) -> None:
    nodes = build_tree(methods)
    first = plan_mount(None, key="k1", nodes=nodes, filters_active=False, selected=None)
    again = plan_mount(
        first, key="k1", nodes=nodes, filters_active=False, selected="N4", stale=True
    )
    assert again.key == "k1"
    assert again.generation == 1
    assert again.widget_key != first.widget_key
    assert again.selection == "N4"
    assert again.open_ids == tuple(ancestor_ids(nodes, "N4"))


def test_every_stale_click_gets_its_own_widget_key(methods: pd.DataFrame) -> None:
    nodes = build_tree(methods)
    mount = plan_mount(None, key="k1", nodes=nodes, filters_active=False, selected=None)
    keys = {mount.widget_key}
    for _ in range(3):
        mount = plan_mount(
            mount, key="k1", nodes=nodes, filters_active=False, selected="4", stale=True
        )
        keys.add(mount.widget_key)
    assert len(keys) == 4


def test_the_stale_flag_changes_nothing_on_a_first_mount(methods: pd.DataFrame) -> None:
    nodes = build_tree(methods)
    mount = plan_mount(
        None, key="k1", nodes=nodes, filters_active=False, selected=None, stale=True
    )
    assert mount.generation == 0


def test_a_new_filter_key_starts_again_at_generation_zero(
    methods: pd.DataFrame,
) -> None:
    nodes = build_tree(methods)
    first = plan_mount(None, key="k1", nodes=nodes, filters_active=False, selected=None)
    stale = plan_mount(
        first, key="k1", nodes=nodes, filters_active=False, selected="4", stale=True
    )
    moved = plan_mount(stale, key="k2", nodes=nodes, filters_active=False, selected="4")
    assert moved.generation == 0
    assert moved.widget_key == "k2"
