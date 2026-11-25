"""URL validation and markdown-safe link helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import quote, urlsplit

from .constants import CODE_TYPES

# scheme://host followed by anything that is not whitespace. ``fullmatch`` is used so
# that a trailing newline cannot slip past the end anchor.
_HTTP_URL = re.compile(r"https?://[^\s/?#]+\S*", re.IGNORECASE)

# Everything a link destination may keep verbatim. Letters and digits are always
# kept; "%" is kept so that existing escapes are not encoded twice. Brackets,
# parentheses, angle brackets, spaces and quotes are left out: they would end a
# markdown link early or open a tag.
_URL_SAFE_CHARS = "-._~:/?#@!$&'*+,;=%"

_ALT_SEPARATOR = re.compile(r"\s+;\s+")
_ALT_KINDS = frozenset(CODE_TYPES) - {"none"}

_HOST_LABELS = MappingProxyType(
    {
        "arxiv.org": "arXiv",
        "doi.org": "DOI",
        "dx.doi.org": "DOI",
        "openreview.net": "OpenReview",
        "openaccess.thecvf.com": "CVF",
        "proceedings.mlr.press": "PMLR",
        "www.sciencedirect.com": "ScienceDirect",
        "sciencedirect.com": "ScienceDirect",
        "ieeexplore.ieee.org": "IEEE Xplore",
    }
)


@dataclass(frozen=True)
class AltCode:
    """A second place to get the same method: its kind and link."""

    kind: str
    url: str


def is_http_url(value: str) -> bool:
    """True for an ``http`` or ``https`` link with a host and no whitespace."""
    return isinstance(value, str) and _HTTP_URL.fullmatch(value) is not None


def safe_url(url: str) -> str:
    """Percent-encode the characters that would break a markdown link destination."""
    return quote(url, safe=_URL_SAFE_CHARS)


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def paper_link_label(url: str) -> str:
    """Short name of the site a paper link points to ("arXiv", "DOI", ...)."""
    host = _host(url)
    if not host:
        return "Paper"
    return _HOST_LABELS.get(host) or host.removeprefix("www.")


def repo_name(url: str) -> str:
    """Repository (or site) name to tell two code links of one method apart."""
    host = _host(url).removeprefix("www.")
    if not host:
        return ""
    if host == "github.com":
        segments = [segment for segment in urlsplit(url).path.split("/") if segment]
        if len(segments) >= 2:
            return segments[1]
        if segments:
            return segments[0]
    return host


def parse_code_alt(raw: str) -> tuple[AltCode, ...]:
    """Parse ``kind|url ; kind|url``; raise ``ValueError`` if an entry is malformed."""
    text = raw.strip()
    if not text:
        return ()
    entries: list[AltCode] = []
    for part in _ALT_SEPARATOR.split(text):
        kind, separator, url = part.strip().partition("|")
        kind, url = kind.strip(), url.strip()
        if not separator or kind not in _ALT_KINDS or not is_http_url(url):
            raise ValueError(f"malformed code_alt entry: {part.strip()!r}")
        entries.append(AltCode(kind=kind, url=url))
    return tuple(entries)
