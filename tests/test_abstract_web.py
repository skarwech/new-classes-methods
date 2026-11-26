"""Abstract fetcher, web client: known hosts only, redirects, limits, retries, spacing."""

from __future__ import annotations

import http.client
import urllib.error
import urllib.request
from collections.abc import Callable

import pytest

from tools import abstract_web
from tools.abstract_web import (
    FAILURE_LIMIT,
    MAX_BODY_BYTES,
    MAX_RETRY_WAIT,
    MAX_TRIES,
    USER_AGENT,
    HostDown,
    HostNotAllowed,
    RateLimited,
    SameSiteRedirects,
    Web,
    check_url,
)

pytestmark = pytest.mark.unit

OPENALEX = "https://api.openalex.org/works/doi:10.1/x"
AT = "\x40"  # written as an escape so that the test URLs are not mistaken for e-mail addresses


class Reply:
    """A stand-in for the object ``urlopen`` returns."""

    def __init__(self, body: bytes = b"ok") -> None:
        self.body = body
        self.asked: list[int] = []

    def __enter__(self) -> Reply:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self, amount: int = -1) -> bytes:
        self.asked.append(amount)
        return self.body if amount < 0 else self.body[:amount]


def opener_returning(reply: Reply) -> Callable[..., Reply]:
    return lambda request, timeout: reply


def http_error(
    url: str, code: int, headers: dict[str, str] | None = None
) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "x", headers or {}, None)  # type: ignore[arg-type]


# --- which addresses may be contacted --------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/x",
        "http://localhost/x",
        "https://api.openalex.org.evil.example/x",
        f"https://api.openalex.org{AT}evil.example/x",
        f"https://user:pw{AT}api.openalex.org/x",
        f"https://user{AT}api.openalex.org/x",  # a name without a password
        "https://api.openalex.org:22/x",
        "https://api.openalex.org:8443/x",
        "http://api.openalex.org/x",
        "file:///etc/passwd",
        "ftp://api.openalex.org/x",
        "https://api.openalex.org:abc/x",  # not a port number
        "https://[broken/x",  # not an address at all
        "https://openaccess.thecvf.com/x\r\nHost: evil.example",  # urlsplit drops these
        "https://api.openalex.org/works/\tx",
        "https://api.openalex.org/x y",
        "https://api.openalex.org/\x7f",
        "https://api.openalex.org/caf\u00e9",  # not ASCII: the caller must encode it
    ],
)
def test_only_https_urls_on_known_hosts_and_the_default_port_are_allowed(
    url: str,
) -> None:
    with pytest.raises(HostNotAllowed):
        check_url(url)
    web = Web(opener=opener_returning(Reply()), sleep=lambda s: None)
    with pytest.raises(HostNotAllowed):
        web(url)


@pytest.mark.parametrize(
    "url",
    [
        OPENALEX,
        "https://export.arxiv.org/api/query?id_list=1",
        "https://api.crossref.org/works/10.1/x",
        "https://openaccess.thecvf.com/content/x.html",
        "https://proceedings.mlr.press/v1/x.html",
        "https://api.openalex.org:443/works",
    ],
)
def test_known_hosts_pass(url: str) -> None:
    check_url(url)


def test_a_redirect_is_followed_only_to_another_allowed_address() -> None:
    handler = SameSiteRedirects()
    request = urllib.request.Request(OPENALEX)
    ok = handler.redirect_request(
        request, None, 302, "Found", {}, "https://api.openalex.org/b"
    )
    assert ok is not None
    assert ok.full_url == "https://api.openalex.org/b"
    for bad in (
        "http://localhost:9/admin",
        "https://evil.example/x",
        "http://api.openalex.org/x",  # a downgrade to plain http
        "https://api.openalex.org:22/x",
        "ftp://api.openalex.org/x",
    ):
        with pytest.raises(HostNotAllowed):
            handler.redirect_request(request, None, 302, "Found", {}, bad)


def test_the_default_opener_uses_the_redirect_check() -> None:
    opener = abstract_web.default_opener()
    assert any(isinstance(h, SameSiteRedirects) for h in opener.handlers)  # type: ignore[attr-defined]


# --- what is sent and what is read ---------------------------------------------------


def test_the_client_sends_a_generic_user_agent_without_contact_details() -> None:
    seen: dict[str, str] = {}

    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        seen.update(dict(request.header_items()))
        return Reply()

    assert Web(opener=opener, sleep=lambda s: None)(OPENALEX) == "ok"
    assert seen == {"User-agent": USER_AGENT}  # nothing else identifies the sender
    assert "@" not in USER_AGENT
    assert "mailto" not in USER_AGENT.lower()


def test_a_body_over_the_limit_is_refused_instead_of_read_whole() -> None:
    web = Web(
        opener=opener_returning(Reply(b"x" * (MAX_BODY_BYTES + 10))),
        sleep=lambda s: None,
    )
    with pytest.raises(OSError, match="too large"):
        web(OPENALEX)
    assert Web(
        opener=opener_returning(Reply(b"x" * MAX_BODY_BYTES)), sleep=lambda s: None
    )(OPENALEX)


def test_a_half_received_answer_is_an_os_error() -> None:
    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        raise http.client.IncompleteRead(b"par")

    with pytest.raises(OSError, match="IncompleteRead"):
        Web(opener=opener, sleep=lambda s: None)(OPENALEX)


def test_the_client_never_asks_for_more_than_the_limit_plus_one_byte() -> None:
    reply = Reply(b"x" * 10)
    Web(opener=opener_returning(reply), sleep=lambda s: None)(OPENALEX)
    assert reply.asked == [MAX_BODY_BYTES + 1]  # enough to see that it was too big


# --- failures ---------------------------------------------------------------------------


def test_a_missing_page_is_none_and_a_busy_server_is_retried_after_a_pause() -> None:
    calls = {"n": 0}

    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        calls["n"] += 1
        if "missing" in request.full_url:
            raise http_error(request.full_url, 404)
        if calls["n"] < 3:
            raise http_error(request.full_url, 429)
        return Reply(b"fine")

    sleeps: list[float] = []
    web = Web(opener=opener, sleep=sleeps.append)
    assert web("https://api.openalex.org/works/missing") is None
    calls["n"] = 0
    assert web("https://api.openalex.org/works/busy") == "fine"
    assert calls["n"] == 3
    assert any(s >= 1 for s in sleeps)


def test_a_timeout_or_a_reset_connection_is_retried_too() -> None:
    calls = {"n": 0}

    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError(TimeoutError("timed out"))
        if calls["n"] == 2:
            raise ConnectionResetError("reset")
        return Reply(b"fine")

    assert Web(opener=opener, sleep=lambda s: None)(OPENALEX) == "fine"
    assert calls["n"] == 3


def test_a_forbidden_answer_is_not_retried_and_a_busy_server_is_given_up_on() -> None:
    attempts = {"n": 0}

    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        attempts["n"] += 1
        raise http_error(
            request.full_url, 403 if "forbidden" in request.full_url else 429
        )

    web = Web(opener=opener, sleep=lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        web("https://api.openalex.org/works/forbidden")
    assert attempts["n"] == 1
    attempts["n"] = 0
    with pytest.raises(urllib.error.HTTPError):
        web("https://api.openalex.org/works/busy")
    assert attempts["n"] == MAX_TRIES


def test_a_busy_server_that_says_how_long_to_wait_is_waited_for() -> None:
    calls = {"n": 0}

    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        calls["n"] += 1
        if calls["n"] == 1:
            raise http_error(request.full_url, 429, {"Retry-After": "37"})
        return Reply(b"fine")

    sleeps: list[float] = []
    assert Web(opener=opener, sleep=sleeps.append)(OPENALEX) == "fine"
    assert max(sleeps) == 37  # not the shorter standard pause


def test_a_pause_that_is_not_a_number_of_seconds_is_ignored() -> None:
    calls = {"n": 0}

    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        calls["n"] += 1
        if calls["n"] == 1:
            raise http_error(
                request.full_url, 503, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
            )
        return Reply(b"fine")

    assert Web(opener=opener, sleep=lambda s: None)(OPENALEX) == "fine"


def test_a_server_that_asks_for_a_long_pause_is_not_waited_for_or_blamed() -> None:
    """A used-up daily quota: retrying is useless, and the host is not down."""
    attempts = {"n": 0}

    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        attempts["n"] += 1
        if "/doi:" not in request.full_url:
            raise http_error(
                request.full_url, 429, {"Retry-After": str(MAX_RETRY_WAIT + 1)}
            )
        return Reply(b"free lookup")

    sleeps: list[float] = []
    web = Web(opener=opener, sleep=sleeps.append)
    with pytest.raises(RateLimited, match="api.openalex.org"):
        web("https://api.openalex.org/works?search=x")
    assert attempts["n"] == 1  # one request, no retries
    assert all(s < MAX_RETRY_WAIT for s in sleeps)  # and no long sleep
    for _ in range(
        FAILURE_LIMIT + 2
    ):  # the host is not "down", however often it is asked
        with pytest.raises(RateLimited):
            web("https://api.openalex.org/works?search=y")
    assert web("https://api.openalex.org/works/doi:10.1/x") == "free lookup"


def test_after_a_long_pause_is_asked_for_the_endpoint_is_not_called_until_it_is_over() -> (
    None
):
    clock = {"now": 1000.0}
    attempts = {"n": 0}

    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        attempts["n"] += 1
        raise http_error(request.full_url, 429, {"Retry-After": "3600"})

    web = Web(opener=opener, sleep=lambda s: None, clock=lambda: clock["now"])
    url = "https://api.openalex.org/works?search=x"
    with pytest.raises(RateLimited):
        web(url)
    clock["now"] += 1800  # half way through
    with pytest.raises(RateLimited, match="30 min"):
        web(url)
    assert attempts["n"] == 1  # the second call made no request
    clock["now"] += 1801  # over
    with pytest.raises(RateLimited):
        web(url)
    assert attempts["n"] == 2  # asked again, and told to wait again


def test_a_long_pause_on_one_lookup_holds_back_the_other_lookups_of_that_kind() -> None:
    attempts = {"n": 0}

    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        attempts["n"] += 1
        raise http_error(request.full_url, 429, {"Retry-After": "3600"})

    web = Web(opener=opener, sleep=lambda s: None)
    with pytest.raises(RateLimited):
        web("https://api.openalex.org/works/doi:10.1/a")
    with pytest.raises(RateLimited):
        web("https://api.openalex.org/works/doi:10.1/b")  # another paper, same endpoint
    assert attempts["n"] == 1


def test_a_rate_limit_message_says_how_long_in_minutes() -> None:
    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        raise http_error(request.full_url, 429, {"Retry-After": "4936"})

    with pytest.raises(RateLimited, match="82 min"):
        Web(opener=opener, sleep=lambda s: None)(OPENALEX)


def test_a_host_that_keeps_failing_is_given_up_on_for_the_rest_of_the_run() -> None:
    calls = {"n": 0}

    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        calls["n"] += 1
        raise urllib.error.URLError("down")

    web = Web(opener=opener, sleep=lambda s: None)
    for _ in range(FAILURE_LIMIT):
        with pytest.raises(OSError, match="down"):
            web(OPENALEX)
    before = calls["n"]
    with pytest.raises(HostDown):
        web(OPENALEX)
    assert calls["n"] == before  # no further attempt was made


def test_the_limit_is_a_handful_of_failures_not_a_never() -> None:
    assert 2 <= FAILURE_LIMIT <= 10


def test_the_failure_count_is_per_host_and_a_success_resets_it() -> None:
    behaviour = {"fail": True}

    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        if behaviour["fail"] and "openalex" in request.full_url:
            raise urllib.error.URLError("down")
        return Reply()

    web = Web(opener=opener, sleep=lambda s: None)
    for _ in range(FAILURE_LIMIT - 1):
        with pytest.raises(OSError, match="down"):
            web(OPENALEX)
    behaviour["fail"] = False
    assert web(OPENALEX) == "ok"  # success: the count starts again
    behaviour["fail"] = True
    for _ in range(FAILURE_LIMIT - 1):
        with pytest.raises(OSError, match="down"):
            web(OPENALEX)
    assert (
        web("https://api.crossref.org/works/10.1/x") == "ok"
    )  # another host is unaffected


# --- spacing ----------------------------------------------------------------------------


def test_the_client_spaces_out_calls_to_the_same_host() -> None:
    clock = {"now": 100.0}
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    web = Web(
        opener=opener_returning(Reply(b"x")), sleep=sleep, clock=lambda: clock["now"]
    )
    web("https://export.arxiv.org/api/query?id_list=1")
    web("https://export.arxiv.org/api/query?id_list=2")
    assert sleeps
    assert sleeps[-1] >= 2.5  # arXiv asks for one call every three seconds


def test_every_known_host_has_a_pause_between_calls() -> None:
    assert set(abstract_web.MIN_INTERVAL) == {
        "export.arxiv.org",
        "api.openalex.org",
        "api.crossref.org",
        "openaccess.thecvf.com",
        "proceedings.mlr.press",
    }
    assert all(seconds > 0 for seconds in abstract_web.MIN_INTERVAL.values())


def test_a_retry_after_with_thousands_of_digits_is_ignored_not_a_crash() -> None:
    calls = {"n": 0}

    def opener(request: urllib.request.Request, timeout: float) -> Reply:
        calls["n"] += 1
        if calls["n"] == 1:
            raise http_error(request.full_url, 429, {"Retry-After": "9" * 5000})
        return Reply(b"fine")

    assert Web(opener=opener, sleep=lambda s: None)(OPENALEX) == "fine"
