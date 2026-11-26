"""The parts of the abstract fetcher that need no network.

Titles and when two of them are the same paper, identifiers in a row of the methods
file, cleaning of abstract text, and one parser for each source.

Standard library only.
"""

from __future__ import annotations

import difflib
import html
import json
import re
import unicodedata
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

# What a line of the abstracts file may say. The site accepts exactly these.
SOURCES = ("arXiv", "OpenAlex", "Crossref", "CVF", "PMLR", "Manual")
MATCHES = ("arxiv id", "doi", "paper url", "title", "manual")
MIN_ABSTRACT_CHARS = 100
MAX_ABSTRACT_CHARS = 8000
MAX_RAW_CHARS = 5 * MAX_ABSTRACT_CHARS  # text with markup; longer is not an abstract
MAX_PAGE_CHARS = 100_000  # of a paper page; the abstract is near the top
MAX_URL_CHARS = 2048
# The site each source's links must be on. A manual line may link anywhere.
SOURCE_HOSTS = {
    "arXiv": ("arxiv.org",),
    "OpenAlex": ("openalex.org", "doi.org"),
    "Crossref": ("doi.org",),
    "CVF": ("openaccess.thecvf.com",),
    "PMLR": ("proceedings.mlr.press",),
}

ID_TITLE_RATIO = 0.9  # an identifier is strong evidence, so titles may differ a little
ID_CONTAINMENT = 0.9  # ... or one may just add a subtitle to the other
ID_CONTAINMENT_MIN_WORDS = 5  # a short title inside a longer one is another paper
ID_TITLE_RATIO_WITH_AUTHOR = (
    0.75  # "GANs" spelled out: the id, an author and a close title
)
SEARCH_TITLE_RATIO = (
    0.93  # a search hit is only trusted when the title is almost identical
)
SEARCH_YEAR_SPREAD = 3  # preprint and journal years can differ
# OpenAlex also holds datasets, peer reviews and errata under the title of a paper. A
# title match must be a paper; "" (the source does not say, as arXiv) is a paper.
PAPER_KINDS = frozenset(
    {
        "",
        "article",
        "preprint",
        "review",
        "book-chapter",
        "book",
        "dissertation",
        "report",
        "letter",
        "conference-paper",
        "proceedings-article",
        "journal-article",
    }
)

# Control, format (zero width, bidi, tags, soft hyphen), lone surrogates (which cannot
# be written as UTF-8), line and paragraph separators.
_HIDDEN = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
_TAG = re.compile(r"<[^>]+>")
_CLOSING_TAG = re.compile(r"</[A-Za-z][\w:.-]*\s*>")
_BLOCK_TAG = re.compile(
    r"<\s*/?\s*(?:\w+:)?(?:p|div|br|li|ul|ol|h[1-6]|title|sec|list|list-item)\b[^>]*>",
    re.IGNORECASE,
)
_TITLE_ELEMENT = re.compile(
    r"<(?:\w+:)?title\b[^>]*>.*?</(?:\w+:)?title>", re.IGNORECASE | re.DOTALL
)
_LABEL = re.compile(r"^(?:(?i:abstract)\s*(?:[.:–—]|-\s)|ABSTRACT\b[.:–—]*)\s*")
_ARXIV_URL = re.compile(
    r"https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/([^?#]+)", re.IGNORECASE
)
_ARXIV_NEW = re.compile(r"[0-9]{4}\.[0-9]{4,5}")
_ARXIV_OLD = re.compile(r"[a-z\-]+(?:\.[A-Z]{2})?/[0-9]{7}")
_VERSION = re.compile(r"v[0-9]+$")
_YEAR = re.compile(r"[0-9]{4}")
_DOI_HOSTS = ("doi.org", "dx.doi.org")
_DOI = re.compile(r"10\.[0-9]+/\S+")


@dataclass(frozen=True)
class Abstract:
    """An abstract found for a method, and where it came from.

    ``title`` is what the source calls the paper; ``method_title`` is the title of the
    method in the methods file the abstract was matched to (empty until matched).
    ``authors``, ``kind`` and ``doi`` are what the source says; a title match is judged
    on them, because a title alone is also the title of a dataset or a review of it.
    """

    text: str
    source: str
    url: str
    matched_by: str
    title: str
    year: int | None = None
    method_title: str = ""
    authors: tuple[str, ...] = ()
    kind: str = ""  # the source's name for the record: article, dataset, ...
    doi: str = ""  # of the record, lower case, without a prefix


# --- titles ---------------------------------------------------------------------------


def normalize_title(text: str) -> str:
    """Lower case, no accents, words separated by single spaces."""
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain.casefold()).split())


def title_similarity(first: str, second: str) -> float:
    """0 to 1; two titles with no letters or digits are never similar."""
    one, two = normalize_title(first), normalize_title(second)
    if not one or not two:
        return 0.0
    return difflib.SequenceMatcher(None, one, two).ratio()


def _contained(first: str, second: str) -> bool:
    """Is (nearly) every word of the shorter title, if it has enough, in the longer?"""
    words_a, words_b = set(normalize_title(first).split()), set(
        normalize_title(second).split()
    )
    short, long_ = (
        (words_a, words_b) if len(words_a) <= len(words_b) else (words_b, words_a)
    )
    if len(short) < ID_CONTAINMENT_MIN_WORDS:
        return False
    return len(short & long_) / len(short) >= ID_CONTAINMENT


def _last_words(surnames: str) -> set[str]:
    """The last word of each surname in a "Rudd; de Rezende Rocha" list, normalized."""
    words = (normalize_title(name).split() for name in surnames.split(";"))
    return {name[-1] for name in words if name}


def _shares_an_author(surnames: str, authors: Sequence[str]) -> bool:
    known = {word for author in authors for word in normalize_title(author).split()}
    return bool(_last_words(surnames) & known)


def _first_author_is(surnames: str, authors: Sequence[str]) -> bool:
    """Is the first author of the method the first author the source lists?"""
    first = normalize_title(surnames.split(";")[0]).split()
    named = normalize_title(authors[0]).split() if authors else []
    return bool(first and first[-1] in named)


def _other_record(row: Mapping[str, str], found: Abstract) -> bool:
    """Is ``found`` a dataset or another work, not the paper of ``row``?"""
    if found.kind not in PAPER_KINDS:
        return True
    wanted = doi_of(row).lower()
    return bool(
        wanted and found.doi and found.doi != wanted and found.kind != "preprint"
    )


def accept(row: Mapping[str, str], found: Abstract) -> bool:
    """Does ``found`` belong to the method in ``row``?

    An identifier is strong evidence, so the titles need only be close, or fairly close
    with the first author in common. A title match is weak evidence: it must also be
    about the same year, a paper (not a dataset) with no other DOI, and written by
    someone the methods file names.
    """
    ratio = title_similarity(row["title"], found.title)
    if found.matched_by != "title":
        if ratio >= ID_TITLE_RATIO or _contained(row["title"], found.title):
            return True
        return ratio >= ID_TITLE_RATIO_WITH_AUTHOR and _first_author_is(
            row.get("authors_surnames", ""), found.authors
        )
    year = row.get("year", "")
    if found.year is None or not _YEAR.fullmatch(year):
        return False
    return (
        ratio >= SEARCH_TITLE_RATIO
        and abs(found.year - int(year)) <= SEARCH_YEAR_SPREAD
        and not _other_record(row, found)
        and _shares_an_author(row.get("authors_surnames", ""), found.authors)
    )


# --- identifiers ----------------------------------------------------------------------


def _arxiv_candidate(text: str) -> str:
    cleaned = re.sub(r"^arxiv:", "", text.strip(), flags=re.IGNORECASE).strip("/")
    return _VERSION.sub("", cleaned.removesuffix(".pdf"))


def arxiv_id_of(row: Mapping[str, str]) -> str:
    """The arXiv id of the method, from its ``arxiv`` column or its paper link."""
    candidates = [row.get("arxiv", "")]
    match = _ARXIV_URL.match(row.get("paper_url", ""))
    if match:
        candidates.append(match.group(1))
    for candidate in map(_arxiv_candidate, candidates):
        if _ARXIV_NEW.fullmatch(candidate) or _ARXIV_OLD.fullmatch(candidate):
            return candidate
    return ""


def _doi_in(text: str) -> str:
    parts = urllib.parse.urlsplit(text)
    if parts.scheme in ("http", "https"):
        found = (
            urllib.parse.unquote(parts.path.lstrip("/"))
            if parts.hostname in _DOI_HOSTS
            else ""
        )
    else:
        found = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    # ASCII digits and no "." or ".." segment: a DOI goes into the path of a request
    dotted = any(segment in (".", "..") for segment in found.split("/"))
    return found if _DOI.fullmatch(found) and not dotted else ""


def bare_doi(text: str) -> str:
    """A DOI as lower case ``10.x/y``, whether given bare or as a doi.org link."""
    return _doi_in(text.strip()).lower()


def doi_of(row: Mapping[str, str]) -> str:
    """The DOI of the method, from its ``doi`` column or a doi.org link."""
    for candidate in (row.get("doi", ""), row.get("paper_url", "")):
        doi = _doi_in(candidate.strip())
        if doi:
            return doi
    return ""


# --- cleaning -------------------------------------------------------------------------


def strip_invisible(text: str) -> str:
    """Remove control and format characters; ordinary whitespace stays."""
    return "".join(
        ch for ch in text if ch.isspace() or unicodedata.category(ch) not in _HIDDEN
    )


def has_hidden_character(text: str) -> bool:
    """Does ``text`` hold a line break, a control character or an invisible one?"""
    return any(unicodedata.category(ch) in _HIDDEN for ch in text)


def deinvert(index: object) -> str:
    """OpenAlex ships abstracts as {word: [positions]}; put the words back in order."""
    if not isinstance(index, Mapping):
        return ""
    placed = sorted(
        (spot, word)
        for word, spots in index.items()
        if isinstance(word, str) and isinstance(spots, Sequence)
        for spot in spots
        if isinstance(spot, int)
    )
    return " ".join(word for _, word in placed)


def _markup_to_text(raw: str) -> str:
    text = _TITLE_ELEMENT.sub(" ", raw)  # a JATS heading such as "Abstract"
    text = _BLOCK_TAG.sub(" ", text)  # paragraphs and line breaks separate words
    return html.unescape(_TAG.sub("", text))  # inline tags (<i>k</i>-nearest) do not


def clean_abstract(raw: str, *, markup: bool = True) -> str:
    """Plain running text, or "" if what is left is too short, too long or damaged.

    ``markup=False`` is for text that is already plain, such as what an XML reader or
    an OpenAlex index gives: a "<" in it is a less-than sign, not the start of a tag.
    """
    if len(raw) > MAX_RAW_CHARS:  # not an abstract; and the patterns below would crawl
        return ""
    text = _markup_to_text(raw) if markup else raw
    text = _LABEL.sub("", " ".join(strip_invisible(text).split()), count=1)
    too_long = len(text) > MAX_ABSTRACT_CHARS  # full text, not an abstract: never cut
    if (
        len(text) < MIN_ABSTRACT_CHARS or too_long or "\ufffd" in text
    ):  # "\ufffd": damaged
        return ""
    return text


def _plain(value: object, *, unescape: bool = True) -> str:
    """A title as one line of text, with nothing the file could not hold."""
    text = str(value or "")
    return " ".join(strip_invisible(html.unescape(text) if unescape else text).split())


def _plain_name(value: object) -> str:
    return _plain(value, unescape=False)


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


# --- the sources ----------------------------------------------------------------------


class _AtomEntries(HTMLParser):
    """Collects id, title, summary and published of every <entry> of an Atom feed.

    This is deliberately not an XML parser: it has no entity or DTD machinery to abuse.
    """

    _FIELDS = frozenset({"id", "title", "summary", "published"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[dict[str, Any]] = []
        self._entry: dict[str, Any] | None = None
        self._field: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "entry":
            self._entry = {"authors": []}
        elif self._entry is not None and tag == "name":
            self._entry["authors"].append("")
            self._field = tag
        elif self._entry is not None and tag in self._FIELDS:
            self._field = tag
            self._entry[tag] = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "entry" and self._entry is not None:
            self.entries.append(self._entry)
            self._entry = None
        elif tag == self._field:
            self._field = None

    def handle_data(self, data: str) -> None:
        if self._entry is None or self._field is None:
            return
        if self._field == "name":
            self._entry["authors"][-1] += data
        else:
            self._entry[self._field] += data


def parse_arxiv_atom(feed: str) -> dict[str, Abstract]:
    """Abstracts in an arXiv API answer, by unversioned arXiv id."""
    reader = _AtomEntries()
    reader.feed(feed)
    reader.close()
    found: dict[str, Abstract] = {}
    for entry in reader.entries:
        link = entry.get("id", "").strip()
        if "/abs/" not in link:
            continue  # the error entry
        arxiv_id = _VERSION.sub("", link.split("/abs/", 1)[1])
        text = clean_abstract(
            entry.get("summary", ""), markup=False
        )  # already unescaped
        if not text:
            continue
        published = entry.get("published", "").strip()[:4]
        found[arxiv_id] = Abstract(
            text=text,
            source="arXiv",
            url=f"https://arxiv.org/abs/{arxiv_id}",
            matched_by="arxiv id",
            title=_plain(entry.get("title", ""), unescape=False),
            year=int(published) if _YEAR.fullmatch(published) else None,
            authors=tuple(name for name in map(_plain_name, entry["authors"]) if name),
        )
    return found


def _openalex_url(work: Mapping[str, Any]) -> str:
    ident = str(work.get("id") or "").strip()
    if ident.startswith("https://"):
        return ident
    doi = str(work.get("doi") or "").strip()
    if doi.startswith("https://"):
        return doi
    return (
        f"https://doi.org/{urllib.parse.quote(doi, safe='/:()')}"
        if doi.startswith("10.")
        else ""
    )


def _openalex_authors(authorships: object) -> tuple[str, ...]:
    if not isinstance(authorships, list):
        return ()
    people = (item.get("author") for item in authorships if isinstance(item, dict))
    names = (
        person.get("display_name") for person in people if isinstance(person, dict)
    )
    return tuple(name for name in map(_plain_name, names) if name)


def openalex_item(work: Mapping[str, Any], *, matched_by: str) -> Abstract | None:
    """An abstract from one OpenAlex work that is already parsed."""
    raw = deinvert(work.get("abstract_inverted_index"))
    # OpenAlex text is plain, except when it was copied from JATS markup.
    abstract = clean_abstract(raw, markup=bool(_CLOSING_TAG.search(raw)))
    url = _openalex_url(work)
    if not abstract or not url:
        return None
    year = work.get("publication_year")
    return Abstract(
        text=abstract,
        source="OpenAlex",
        url=url,
        matched_by=matched_by,
        title=_plain(work.get("title")),
        year=year if isinstance(year, int) and not isinstance(year, bool) else None,
        authors=_openalex_authors(work.get("authorships")),
        kind=_plain(work.get("type")),
        doi=bare_doi(str(work.get("doi") or "")),
    )


def parse_openalex_work(text: str, *, matched_by: str) -> Abstract | None:
    work = _json(text)
    return (
        openalex_item(work, matched_by=matched_by) if isinstance(work, dict) else None
    )


def parse_crossref_work(text: str, doi: str) -> Abstract | None:
    payload = _json(text)
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict):
        return None
    abstract = clean_abstract(str(message.get("abstract") or ""))
    if not abstract:
        return None
    titles = message.get("title")
    return Abstract(
        text=abstract,
        source="Crossref",
        url=f"https://doi.org/{urllib.parse.quote(doi, safe='/:()')}",
        matched_by="doi",
        title=_plain(titles[0]) if isinstance(titles, list) and titles else "",
    )


def _page(
    page: str, url: str, source: str, title_pattern: str, abstract_pattern: str
) -> Abstract | None:
    page = page[:MAX_PAGE_CHARS]
    abstract = re.search(abstract_pattern, page, re.DOTALL)
    title = re.search(title_pattern, page, re.DOTALL)
    text = clean_abstract(abstract.group(1)) if abstract else ""
    if not text or not title:
        return None
    return Abstract(
        text=text,
        source=source,
        url=url,
        matched_by="paper url",
        title=_plain(_TAG.sub(" ", title.group(1))),
    )


def parse_cvf(page: str, url: str) -> Abstract | None:
    return _page(
        page,
        url,
        "CVF",
        r'<div id="papertitle">\s*([^<]*)',
        r'<div id="abstract">(.*?)</div>',
    )


def parse_pmlr(page: str, url: str) -> Abstract | None:
    return _page(
        page, url, "PMLR", r"<h1>(.*?)</h1>", r'<div id="abstract"[^>]*>(.*?)</div>'
    )


def url_problem(source: str, url: str) -> str:
    """Why ``url`` may not be the link of a line from ``source``; "" if it may.

    Any line needs a real http(s) host and no user name; a line from a source other than
    ``Manual`` must be https on that source's own site. The site applies the same rule.
    """
    if not url or len(url) > MAX_URL_CHARS or any(ch.isspace() for ch in url):
        return "is empty, too long or has a space"
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return "is not a link"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "is not an http(s) link"
    if parts.username is not None or parts.password is not None:
        return "has a user name in it"
    hosts = SOURCE_HOSTS.get(source)
    if hosts is None:
        return ""
    if (
        parts.scheme != "https"
        or port not in (None, 443)
        or parts.hostname not in hosts
    ):
        return f"is not an https link on {' or '.join(hosts)}, where {source} lives"
    return ""
