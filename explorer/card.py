"""Content of the detail card, as plain functions from one table row to text.

Everything that comes from the CSV is escaped before it is put into markdown, so
that a stray ``*``, ``_``, ``[``, ``$`` or ``#`` in a title cannot change the layout
or start math. Escaping cannot stop the renderer from turning ``:name:`` into an emoji
or a web address into a link, so the loader refuses such text instead (see
``data.py``). The reference for copying is plain text and is not escaped. An abstract
is third-party text of any shape, so it is not put into markdown at all: it is HTML
escaped and shown as one paragraph (``abstract_html``).
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping

from .constants import CHECK_LABELS, CODE_LABELS
from .links import AltCode, paper_link_label, parse_code_alt, repo_name, safe_url

Row = Mapping[str, str]

_HARD_BREAK = "  \n"

# The label above the copyable reference; the page puts the abstract before it.
REFERENCE_LABEL = "**Reference**"

# Characters that format text inline in markdown ("$" starts math in Streamlit).
_INLINE_SPECIALS = re.compile(r"([\\`*_\[\]<>~$|&#])")
# In Streamlit ":smile:" is an emoji and ":red[text]" a color; a plain colon is not.
# This runs after "[" has been escaped, hence the optional backslash before it.
_COLON_DIRECTIVE = re.compile(r":(?=[\w+\-/]+(?::|\\?\[))")
# A line that would start a list or an ordered list.
_BLOCK_MARKER = re.compile(r"([+\-]|\d+[.)])(?=\s|$)")
# A line of only "=" or "-" would underline the line above it as a heading or be a rule.
_UNDERLINE = re.compile(r"(?:=+|-{2,})\s*$")


def _escape_block_marker(text: str) -> str:
    if _UNDERLINE.match(text):
        return f"\\{text}"
    match = _BLOCK_MARKER.match(text)
    if match is None:
        return text
    marker = match.group(1)
    if marker[0].isdigit():
        return f"{marker[:-1]}\\{marker[-1]}{text[len(marker):]}"
    return f"\\{text}"


def md_escape(text: str) -> str:
    """Make ``text`` safe to show as plain text inside markdown."""
    escaped = _INLINE_SPECIALS.sub(r"\\\1", text)
    escaped = _COLON_DIRECTIVE.sub(r"\\:", escaped)
    return _escape_block_marker(escaped)


def _link(label: str, url: str) -> str:
    return f"[{md_escape(label)}]({safe_url(url)})"


def _sentence(text: str) -> str:
    return text if text.endswith((".", "?", "!")) else f"{text}."


# --- authors, byline, reference -------------------------------------------------------


def author_names(row: Row) -> str:
    """Surnames joined with commas, plus "et al." when the author list is incomplete."""
    surnames = [
        name.strip() for name in row["authors_surnames"].split(";") if name.strip()
    ]
    if not surnames:
        return ""
    names = ", ".join(surnames)
    return f"{names} et al." if row["authors_complete"] == "no" else names


def byline(row: Row) -> str:
    """ "Surnames (year)" as markdown; empty when no authors are recorded."""
    names = author_names(row)
    return f"{md_escape(names)} ({row['year']})" if names else ""


def reference_text(row: Row) -> str:
    """The reference as plain text, ready to copy: authors (year). Title. Venue."""
    names, year = author_names(row), row["year"]
    title, venue = row["title"].strip(), row["venue"].strip()
    if names:
        parts = [f"{names} ({year})", title, venue]
    else:
        parts = [f"{title} ({year})" if title else f"({year})", venue]
    return " ".join(_sentence(part) for part in parts if part)


# --- links ----------------------------------------------------------------------------


def _paper_line(row: Row) -> str:
    url = row["paper_url"]
    if not url:
        return "**Paper:** no link recorded"
    return f"**Paper:** {_link(paper_link_label(url), url)}"


def _alternative_link(entry: AltCode) -> str:
    name = repo_name(entry.url)
    label = CODE_LABELS[entry.kind] + (f" ({name})" if name else "")
    return _link(label, entry.url)


def _code_lines(row: Row) -> list[str]:
    kind, url = row["code_type"], row["code_url"]
    if kind == "none" or not url:
        lines = [f"**Code:** {CODE_LABELS['none']}"]
    else:
        lines = [f"**Code:** {_link(CODE_LABELS[kind], url)}"]
    alternatives = parse_code_alt(row["code_alt"])
    if alternatives:
        lines.append(
            "Also: " + "; ".join(_alternative_link(entry) for entry in alternatives)
        )
    return lines


# --- the card -------------------------------------------------------------------------


def card_markdown(row: Row) -> str:
    """The name, details and links of the card as markdown; no abstract or reference."""
    title = f"*{md_escape(row['title'])}*" if row["title"] else ""
    details = [line for line in (byline(row), title, md_escape(row["venue"])) if line]
    blocks = [f"### {md_escape(row['method'])}"]
    if details:
        blocks.append(_HARD_BREAK.join(details))
    links = [
        _paper_line(row),
        *_code_lines(row),
        f"**Reference check:** {CHECK_LABELS[row['check']]}",
    ]
    blocks.append(_HARD_BREAK.join(links))
    return "\n\n".join(blocks)


# --- the abstract ---------------------------------------------------------------------


def abstract_text(row: Row) -> str:
    return row.get("abstract", "").strip()


def abstract_heading(row: Row) -> str:
    """The label above the abstract; for a method without one, the whole line."""
    return "**Abstract**" if abstract_text(row) else "**Abstract:** none recorded"


def abstract_html(row: Row) -> str:
    """The abstract as one paragraph of escaped text: no markdown, markup or links."""
    text = abstract_text(row)
    return f"<p>{html.escape(text, quote=False)}</p>" if text else ""


def abstract_source_markdown(row: Row) -> str:
    """ "Source: arXiv" with a link to the record the abstract was taken from."""
    if not abstract_text(row) or not row.get("abstract_url"):
        return ""
    return f"*Source: {_link(row['abstract_source'], row['abstract_url'])}*"
