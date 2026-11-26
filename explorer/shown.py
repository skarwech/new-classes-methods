"""How a value from a data file is shown in an error message."""

from __future__ import annotations

MAX_SHOWN_CHARS = 60


def show(value: str) -> str:
    """``repr(value)``, cut short, so that a huge cell cannot make a huge message."""
    text = repr(value)
    return (
        text if len(text) <= MAX_SHOWN_CHARS else text[: MAX_SHOWN_CHARS - 1] + "\u2026"
    )
