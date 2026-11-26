"""Shared constants: column names, vocabularies, display labels and layout numbers."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

SITE_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = SITE_ROOT / "data" / "methods_public.csv"

PUBLIC_COLUMNS: tuple[str, ...] = (
    "id",
    "tree_family",
    "tree_section",
    "tree_type",
    "method",
    "year",
    "authors_surnames",
    "authors_complete",
    "title",
    "venue",
    "doi",
    "arxiv",
    "paper_url",
    "code_url",
    "code_type",
    "code_alt",
    "check",
)

# Code availability: stored value -> label shown to visitors.
CODE_LABELS = MappingProxyType(
    {
        "official": "Official code",
        "third-party": "Third-party implementation",
        "library": "Library implementation",
        "none": "No public code found",
    }
)
CODE_TYPES: tuple[str, ...] = tuple(CODE_LABELS)

# State of the reference: stored value -> label shown to visitors.
CHECK_LABELS = MappingProxyType(
    {
        "V": "Checked against the source",
        "C": "Not re-checked",
        "C?": "Incomplete or flagged: check before citing",
    }
)
CHECK_VALUES: tuple[str, ...] = tuple(CHECK_LABELS)

# The same states as short names for the sidebar filter, where long ones are cut off.
CHECK_FILTER_LABELS = MappingProxyType(
    {
        "V": "Checked against the source",
        "C": "Not re-checked",
        "C?": "Incomplete or flagged",
    }
)

AUTHORS_COMPLETE_VALUES: tuple[str, ...] = ("yes", "no")

# Abstracts live in data/abstracts.csv, next to the methods file; attached by id.
ABSTRACTS_FILE_NAME = "abstracts.csv"
ABSTRACT_FIELDS: tuple[str, ...] = (
    "abstract",
    "abstract_source",
    "abstract_url",
    "abstract_match",
)
# Where an abstract came from ("Manual": typed in by the collection's author) and how it
# was matched to the method.
ABSTRACT_SOURCES: tuple[str, ...] = (
    "arXiv",
    "OpenAlex",
    "Crossref",
    "CVF",
    "PMLR",
    "Manual",
)
ABSTRACT_MATCHES: tuple[str, ...] = ("arxiv id", "doi", "paper url", "title", "manual")
MAX_ABSTRACT_CHARS = 8000
MAX_ABSTRACT_URL_CHARS = 2048
# The site each source's links must be on; a "Manual" line may link anywhere.
ABSTRACT_SOURCE_HOSTS: dict[str, tuple[str, ...]] = {
    "arXiv": ("arxiv.org",),
    "OpenAlex": ("openalex.org", "doi.org"),
    "Crossref": ("doi.org",),
    "CVF": ("openaccess.thecvf.com",),
    "PMLR": ("proceedings.mlr.press",),
}

# Deep link: ?m=<id> opens that method with its ancestors expanded.
SELECTED_PARAM = "m"
MAX_ID_LENGTH = 32

# Search box.
MAX_QUERY_CHARS = 300

# Tree component (pixels).
TREE_HEIGHT = 620
TREE_ROW_HEIGHT = 28
TREE_INDENT = 16

# Main area: tree on the left, card on the right.
LAYOUT_RATIO: tuple[int, int] = (5, 4)
