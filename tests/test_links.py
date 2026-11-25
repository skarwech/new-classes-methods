"""URL validation, markdown-safe encoding, and code_alt parsing."""

from __future__ import annotations

import pytest

from explorer.links import (
    AltCode,
    is_http_url,
    paper_link_label,
    parse_code_alt,
    repo_name,
    safe_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://arxiv.org/abs/1511.06233",
        "http://example.org/a",
        "HTTPS://EXAMPLE.ORG/A",
        "https://doi.org/10.1002/(SICI)1097-0258(19980815/30)17:15/16<1661::AID-SIM968>3.0.CO;2-2",
    ],
)
def test_is_http_url_accepts_web_links(url: str) -> None:
    assert is_http_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "",
        " ",
        "ftp://example.org/a",
        "javascript:alert(1)",
        "data:text/html,<script>1</script>",
        "//example.org/a",
        "https://",
        "https:///path",
        "https://example.org/with space",
        "https://example.org/a\nb",
        "mailto:someone@example.org",
    ],
)
def test_is_http_url_rejects_everything_else(url: str) -> None:
    assert not is_http_url(url)


def test_safe_url_leaves_ordinary_urls_untouched() -> None:
    for url in (
        "https://arxiv.org/abs/1511.06233",
        "https://openreview.net/pdf?id=IBVBtz_sRSm",
        "https://github.com/Jingkang50/OpenOOD/blob/HEAD/openood/trainers/arpl_trainer.py",
        "https://example.org/a#section-2",
        "https://example.org/it's",
    ):
        assert safe_url(url) == url


def test_safe_url_encodes_characters_that_break_markdown_links() -> None:
    assert safe_url("https://x.org/a_(b)") == "https://x.org/a_%28b%29"
    assert safe_url("https://x.org/a<b>c") == "https://x.org/a%3Cb%3Ec"
    assert safe_url("https://x.org/a[b]") == "https://x.org/a%5Bb%5D"
    assert safe_url("https://x.org/a b") == "https://x.org/a%20b"


def test_safe_url_does_not_double_encode() -> None:
    assert safe_url("https://x.org/a%28b%29") == "https://x.org/a%28b%29"
    assert safe_url(safe_url("https://x.org/a_(b)")) == "https://x.org/a_%28b%29"


@pytest.mark.parametrize(
    ("url", "label"),
    [
        ("https://arxiv.org/abs/1511.06233", "arXiv"),
        ("https://doi.org/10.1109/TPAMI.2012.256", "DOI"),
        ("https://dx.doi.org/10.1109/TPAMI.2012.256", "DOI"),
        ("https://openreview.net/forum?id=tXwNRz73zr", "OpenReview"),
        ("https://openaccess.thecvf.com/content/CVPR2021/papers/x.pdf", "CVF"),
        ("https://proceedings.mlr.press/v199/schaeffer22a.html", "PMLR"),
        (
            "https://www.sciencedirect.com/science/article/abs/pii/S0004370223001583",
            "ScienceDirect",
        ),
        ("https://ieeexplore.ieee.org/document/9521769", "IEEE Xplore"),
        ("https://www.example.org/paper", "example.org"),
        ("not a url", "Paper"),
    ],
)
def test_paper_link_label(url: str, label: str) -> None:
    assert paper_link_label(url) == label


@pytest.mark.parametrize(
    ("url", "name"),
    [
        (
            "https://github.com/Jingkang50/OpenOOD/blob/HEAD/openood/postprocessors/x.py",
            "OpenOOD",
        ),
        ("https://github.com/Vastlab/libsvm-openset", "libsvm-openset"),
        ("https://github.com/owner", "owner"),
        ("https://github.com", "github.com"),
        ("https://www.lamda.nju.edu.cn/code_SENCForest.ashx", "lamda.nju.edu.cn"),
        ("garbage", ""),
    ],
)
def test_repo_name(url: str, name: str) -> None:
    assert repo_name(url) == name


def test_a_malformed_host_gives_neutral_results_instead_of_an_error() -> None:
    assert paper_link_label("http://[::1") == "Paper"
    assert repo_name("http://[::1") == ""


def test_parse_code_alt_empty_means_no_alternatives() -> None:
    assert parse_code_alt("") == ()
    assert parse_code_alt("   ") == ()


def test_parse_code_alt_single_and_multiple_entries() -> None:
    one = "library|https://github.com/a/b/blob/HEAD/x.py"
    assert parse_code_alt(one) == (
        AltCode("library", "https://github.com/a/b/blob/HEAD/x.py"),
    )
    two = one + " ; third-party|https://github.com/c/d"
    assert parse_code_alt(two) == (
        AltCode("library", "https://github.com/a/b/blob/HEAD/x.py"),
        AltCode("third-party", "https://github.com/c/d"),
    )


def test_parse_code_alt_tolerates_extra_whitespace() -> None:
    parsed = parse_code_alt(
        "  official|https://github.com/a/b  ;  library|https://github.com/c/d "
    )
    assert [entry.kind for entry in parsed] == ["official", "library"]


@pytest.mark.parametrize(
    "raw",
    [
        "https://github.com/a/b",  # no type
        "library|",  # no url
        "|https://github.com/a/b",  # no type
        "none|https://github.com/a/b",  # 'none' is not an implementation
        "weird|https://github.com/a/b",  # unknown type
        "library|ftp://example.org/x",  # not http(s)
        "library|javascript:alert(1)",
        "library|https://github.com/a/b ; oops",  # second entry malformed
    ],
)
def test_parse_code_alt_rejects_malformed_entries(raw: str) -> None:
    with pytest.raises(ValueError, match="malformed code_alt entry"):
        parse_code_alt(raw)
