"""Which method is selected.

Three places can say: the session (what was clicked), the address (``?m=<id>``) and
the tree component (what it returns after a click). The component's answer is stored
in the session by a callback, so the rules reduce to one: the session wins and the
address only seeds it. Everything that comes from outside is checked against the
known method ids.
"""

from __future__ import annotations

from collections.abc import Container, MutableMapping
from typing import Any

from .constants import MAX_ID_LENGTH


def valid_id(raw: object, known: Container[str]) -> str | None:
    """``raw`` if it is a known method id, else ``None`` (also for non-text)."""
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not candidate or len(candidate) > MAX_ID_LENGTH:
        return None
    return candidate if candidate in known else None


def clicked_id(component_value: Any, known: Container[str]) -> str | None:
    """The method id in the tree's node dict; folders and junk give ``None``."""
    if not isinstance(component_value, dict):
        return None
    return valid_id(component_value.get("id"), known)


def resolve_selection(
    *, current: str | None, url: object, known: Container[str]
) -> str | None:
    """The selected method: the remembered one if valid, else the one in the address."""
    if current is not None and current in known:
        return current
    return valid_id(url, known)


def remember_click(
    state: MutableMapping[str, Any],
    widget_key: str,
    known: Container[str],
    selected_key: str,
    *,
    current_widget_key: str | None = None,
    stale_key: str | None = None,
) -> None:
    """Callback body: copy a clicked method from the tree's widget value into ``state``.

    This is the only place where a click becomes the remembered selection. Folders,
    unknown ids and anything that is not a node leave the earlier selection as it was.

    If ``state[current_widget_key]`` names a different tree than the one clicked, the
    click came from a tree that has since been replaced: ``state[stale_key]`` is set so
    that the next run mounts a tree that shows the selection.
    """
    picked = clicked_id(state.get(widget_key), known)
    if picked is None:
        return
    state[selected_key] = picked
    if (
        stale_key is not None
        and current_widget_key is not None
        and widget_key != state.get(current_widget_key)
    ):
        state[stale_key] = True
