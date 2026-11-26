"""Fixed wording shown on the page. Plain text only: no emoji, icons or images."""

from __future__ import annotations

TITLE = "Handling New Classes in Production"


def description(count: int) -> str:
    """Two lines under the title."""
    first = (
        f"{count} methods for recognizing, discovering, integrating and adapting "
        "to classes that a model did not see in training, shown as a tree."
    )
    second = (
        "Select a method to see its reference, a link to the paper and a link to "
        "the code. Search and filters are in the sidebar (on a phone, open it with "
        "the arrow at the top left)."
    )
    return f"{first}  \n{second}"


HOW_TO_READ = """\
**Tree.** Methods are grouped by what a system does with a class it was not \
trained on: Unknown Rejection, Class Discovery, Model Integration and Stream \
Adaptation, followed by references for pipeline components. Each folder shows how \
many methods it holds. Click a folder to open it and a method to see its details.

**Code.**

- Official code: the authors' own repository. It is accepted when its README says \
so, when a paper author appears among the commit authors, or when the paper itself \
links it.
- Third-party implementation: a repository whose README names the paper but whose \
owner is not an author.
- Library implementation: the method is implemented in a maintained library; the \
link goes to the file that defines it.
- No public code found: no repository was verified. This is not proof that none \
exists.
- Also: a second place to get the same method, for example a library version next to \
the authors' repository.

**Reference check.**

- Checked against the source: authors and title were verified from the BibTeX in \
the authors' README or from a publication record.
- Not re-checked: the reference was not verified again. Authors and titles are the \
standard ones; check volumes and pages before citing.
- Incomplete or flagged: check before citing. The entry was flagged, or its author \
list or venue could not be completed.

**Abstracts.** Abstracts were retrieved automatically from arXiv, OpenAlex, Crossref \
and the open pages of CVF and PMLR, and each was checked against the title of the \
method. Every abstract shows its source. Some methods have none, because no open \
source carries it.

**Papers.** Some methods have no paper link, because no link could be verified; for \
those only the reference is shown. When the author list is incomplete, the \
reference ends it with "et al."
""".strip()

# Sidebar.
SIDEBAR_HEADER = "Search and filters"
SEARCH_LABEL = "Search"
SEARCH_HINT = "Looks at method names, authors and titles. Accents and case are ignored."
FAMILY_LABEL = "Family"
CODE_FILTER_LABEL = "Code availability"
CHECK_FILTER_LABEL = "Reference check"
YEAR_LABEL = "Year"
DOWNLOAD_LABEL = "Download filtered rows (CSV)"
DOWNLOAD_FILE_NAME = "methods_filtered.csv"

# Messages.
NO_MATCH = (
    "No methods match the current search and filters. "
    "Clear the search or a filter to see more."
)
DATA_ERROR = "The data file could not be loaded, so the collection cannot be shown."
HOW_TO_READ_LABEL = "How to read"


def count_text(shown: int, total: int) -> str:
    """ "N of 170 methods"."""
    return f"{shown} of {total} methods"
