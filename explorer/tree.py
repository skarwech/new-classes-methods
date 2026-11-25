"""Build the collapsible tree from the (filtered) methods table and plan its mount.

A node is a plain dict that the tree component reads: ``{"id", "name"}`` for a method
and ``{"id", "name", "children"}`` for a folder. Folders are grouped by first
appearance in the table, so the order of the CSV is the order on screen.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

import pandas as pd

from .filters import Filters

Node = dict[str, Any]

FAMILY_PREFIX = "family:"
SECTION_PREFIX = "section:"
TYPE_PREFIX = "type:"

# Folder ids carry the whole path from the family down, joined with a control
# character that the loader refuses in the data, so no two folders can share an id
# and no folder id can equal a method id (method ids never contain a colon).
_PATH_SEPARATOR = "\x1f"


def family_id(family: str) -> str:
    return f"{FAMILY_PREFIX}{family}"


def section_id(family: str, section: str) -> str:
    return f"{SECTION_PREFIX}{family}{_PATH_SEPARATOR}{section}"


def type_id(family: str, section: str, kind: str) -> str:
    return f"{TYPE_PREFIX}{family}{_PATH_SEPARATOR}{section}{_PATH_SEPARATOR}{kind}"


# A name that already ends in a year, such as "Ledoit & Wolf (2004)" or "... (2021/22)".
_TRAILING_YEAR = re.compile(r"\(\d{4}(?:/\d{2,4})?\)\s*$")


class _Entry(NamedTuple):
    id: str
    family: str
    section: str
    type: str
    label: str


@dataclass(frozen=True)
class TreeMount:
    """What the tree is told when mounted; held constant until it is remounted."""

    key: str
    selection: str | None
    open_ids: tuple[str, ...]
    generation: int = 0

    @property
    def widget_key(self) -> str:
        """The widget key: the filter key, plus a counter after a stale click."""
        return self.key if self.generation == 0 else f"{self.key}~{self.generation}"


# --- labels ---------------------------------------------------------------------------


def leaf_label(method: str, year: str) -> str:
    """ "OpenMax (2016)"; a name that already ends in a year is left as it is."""
    return method if _TRAILING_YEAR.search(method) else f"{method} ({year})"


def folder_label(name: str, count: int) -> str:
    return f"{name} ({count})"


# --- nodes ----------------------------------------------------------------------------


def is_folder(node: Mapping[str, Any]) -> bool:
    return "children" in node


def count_leaves(node: Mapping[str, Any]) -> int:
    """1 for a method; the number of methods below a folder."""
    if not is_folder(node):
        return 1
    return sum(count_leaves(child) for child in node["children"])


def _folder(node_id: str, name: str, children: list[Node]) -> Node:
    count = sum(count_leaves(child) for child in children)
    return {"id": node_id, "name": folder_label(name, count), "children": children}


def _leaf(entry: _Entry) -> Node:
    return {"id": entry.id, "name": entry.label}


def _section_children(
    family: str, section: str, entries: Sequence[_Entry]
) -> list[Node]:
    """Type folders and loose methods of one section, in order of first appearance."""
    order: list[_Entry | str] = []
    by_type: dict[str, list[_Entry]] = {}
    for entry in entries:
        if not entry.type:
            order.append(entry)
            continue
        if entry.type not in by_type:
            by_type[entry.type] = []
            order.append(entry.type)
        by_type[entry.type].append(entry)
    return [
        (
            _leaf(item)
            if isinstance(item, _Entry)
            else _folder(
                type_id(family, section, item),
                item,
                [_leaf(e) for e in by_type[item]],
            )
        )
        for item in order
    ]


def build_tree(frame: pd.DataFrame) -> list[Node]:
    """Family -> section -> optional type -> method, from the rows of ``frame``.

    The frame is not modified; an empty frame gives an empty tree.
    """
    families: dict[str, dict[str, list[_Entry]]] = {}
    columns = zip(
        frame["id"],
        frame["tree_family"],
        frame["tree_section"],
        frame["tree_type"],
        frame["method"],
        frame["year"],
        strict=True,
    )
    for row_id, family, section, kind, method, year in columns:
        entry = _Entry(row_id, family, section, kind, leaf_label(method, year))
        families.setdefault(family, {}).setdefault(section, []).append(entry)
    return [
        _folder(
            family_id(family),
            family,
            [
                _folder(
                    section_id(family, section),
                    section,
                    _section_children(family, section, entries),
                )
                for section, entries in sections.items()
            ],
        )
        for family, sections in families.items()
    ]


# --- reading a tree -------------------------------------------------------------------


def _walk(nodes: Sequence[Node]) -> Iterator[Node]:
    for node in nodes:
        yield node
        yield from _walk(node.get("children", ()))


def leaf_ids(nodes: Sequence[Node]) -> list[str]:
    """Ids of all methods, depth first."""
    return [node["id"] for node in _walk(nodes) if not is_folder(node)]


def folder_ids(nodes: Sequence[Node]) -> list[str]:
    """Ids of all folders, depth first."""
    return [node["id"] for node in _walk(nodes) if is_folder(node)]


def _path_to(nodes: Sequence[Node], leaf_id: str) -> list[str] | None:
    for node in nodes:
        if not is_folder(node):
            if node["id"] == leaf_id:
                return []
            continue
        below = _path_to(node["children"], leaf_id)
        if below is not None:
            return [node["id"], *below]
    return None


def ancestor_ids(nodes: Sequence[Node], leaf_id: str) -> list[str]:
    """Folder ids from the top down to method ``leaf_id``; empty if it is not here."""
    return _path_to(nodes, leaf_id) or []


# --- mounting -------------------------------------------------------------------------


def folders_to_open(
    nodes: Sequence[Node], *, filters_active: bool, selected: str | None
) -> tuple[str, ...]:
    """Folders that are open when the tree is mounted.

    With a filter every remaining folder has a match, so all are opened. Without one,
    only the ancestors of the selected method are: the tree can highlight a method
    only if it is visible.
    """
    if filters_active:
        return tuple(folder_ids(nodes))
    if selected is None:
        return ()
    return tuple(ancestor_ids(nodes, selected))


def tree_key(filters: Filters) -> str:
    """Widget key: changes exactly when the filters change, which remounts the tree."""
    digest = hashlib.blake2s(
        filters.signature().encode("utf-8"), digest_size=6
    ).hexdigest()
    return f"tree-{digest}"


def plan_mount(
    previous: TreeMount | None,
    *,
    key: str,
    nodes: Sequence[Node],
    filters_active: bool,
    selected: str | None,
    stale: bool = False,
) -> TreeMount:
    """The props for this run. While the key is unchanged they stay as they were.

    The component re-applies its ``selection`` prop whenever that prop changes, which
    re-fires its selection event and can start a loop of reruns. Holding the props
    constant for the life of a mount avoids that; the component keeps track of later
    clicks on its own.

    ``stale`` says that a click came from a tree that had already been replaced (the
    visitor typed a search term and clicked a row before the new tree arrived). That
    click is remembered but the new tree cannot know it, so a fresh tree is mounted
    under a new widget key with the selection it should show.
    """
    same_filters = previous is not None and previous.key == key
    if same_filters and not stale:
        return previous
    generation = previous.generation + 1 if same_filters and previous else 0
    visible = (
        selected if selected is not None and selected in set(leaf_ids(nodes)) else None
    )
    return TreeMount(
        key=key,
        selection=visible,
        open_ids=folders_to_open(
            nodes, filters_active=filters_active, selected=visible
        ),
        generation=generation,
    )
