"""The web client of the abstract fetcher.

It contacts a short list of hosts over https only, follows a redirect only to another
allowed address, reads at most ``MAX_BODY_BYTES`` of an answer, spaces calls to the same
host, retries what is worth retrying and gives up on a host that keeps failing. It sends
a generic User-Agent and no contact details.

Standard library only.
"""

from __future__ import annotations

import http.client
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from email.message import Message
from typing import IO, Any

USER_AGENT = "methods-abstract-fetch/1.0"
TIMEOUT_SECONDS = 60
MAX_TRIES = 4
MAX_BODY_BYTES = 2_000_000
FAILURE_LIMIT = 5  # consecutive failed calls to one host before it is given up on
RETRY_CODES = frozenset({429, 500, 502, 503, 504})
BACKOFF_SECONDS = 5.0
MAX_RETRY_WAIT = 120  # seconds; a server that asks for more is not waited for

# Hosts the program may contact, and the least time between two calls to each.
MIN_INTERVAL: dict[str, float] = {
    "export.arxiv.org": 3.0,  # the API asks for one call every three seconds
    "api.openalex.org": 0.2,
    "api.crossref.org": 1.0,
    "openaccess.thecvf.com": 0.5,
    "proceedings.mlr.press": 0.5,
}


class HostNotAllowed(ValueError):
    """The program was asked to contact an address it has no reason to contact."""


class HostDown(OSError):
    """A host failed so many times in a row that it is not asked again."""


class RateLimited(OSError):
    """A host asked for a pause too long to wait for, such as a used-up daily quota."""


def check_url(url: str) -> None:
    """Raise ``HostNotAllowed`` unless ``url`` is https, on a known host and port."""
    if not url.isascii() or any(ch <= " " or ch == "\x7f" for ch in url):
        # urlsplit would drop a tab or a line break; a caller must encode the rest
        raise HostNotAllowed(f"not an address this program contacts: {url[:60]!r}")
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise HostNotAllowed(
            f"not an address this program contacts: {url[:60]}"
        ) from error
    allowed = (
        parts.scheme == "https"
        and parts.hostname in MIN_INTERVAL
        and port in (None, 443)
        and parts.username is None
        and parts.password is None
    )
    if not allowed:
        raise HostNotAllowed(f"not an address this program contacts: {url[:60]}")


class SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only when the new address passes ``check_url``."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> urllib.request.Request | None:
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(SameSiteRedirects())


class Web:
    """``Web()(url)`` is the text at ``url``, or None for a missing page."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._opener = opener if opener is not None else default_opener().open
        self._sleep, self._clock = sleep, clock
        self._last_call: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        self._paused_until: dict[tuple[str, str], float] = {}

    def __call__(self, url: str) -> str | None:
        check_url(url)
        host = urllib.parse.urlsplit(url).hostname or ""
        if self._failures.get(host, 0) >= FAILURE_LIMIT:
            raise HostDown(
                f"{host} failed {FAILURE_LIMIT} times in a row; not asked again"
            )
        self._check_not_paused(url, host)
        body = self._get(url, host)
        if body is not None and len(body) > MAX_BODY_BYTES:
            raise OSError(
                f"answer from {host} is too large (over {MAX_BODY_BYTES} bytes)"
            )
        return None if body is None else body.decode("utf-8", errors="replace")

    def _get(self, url: str, host: str) -> bytes | None:
        request = urllib.request.Request(  # noqa: S310 - https and host were checked
            url, headers={"User-Agent": USER_AGENT}
        )
        for attempt in range(1, MAX_TRIES + 1):
            self._wait_for_turn(host)
            try:
                with self._opener(request, timeout=TIMEOUT_SECONDS) as reply:
                    body: bytes = reply.read(MAX_BODY_BYTES + 1)
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    self._failures[host] = 0  # the host answered
                    return None
                if error.code not in RETRY_CODES:
                    raise  # not a sign that the host is down
                pause = _retry_after(error)
                if pause is not None and pause > MAX_RETRY_WAIT:
                    self._failures[host] = 0  # it answered, so it is up
                    self._paused_until[_endpoint(url)] = self._clock() + pause
                    raise RateLimited(
                        f"{host} asks for a pause of {pause // 60} min; try again later"
                    ) from error
                self._after_failure(host, attempt, error, pause)
            except (OSError, http.client.HTTPException) as error:
                self._after_failure(host, attempt, _as_os_error(error))
            else:
                self._failures[host] = 0
                return body
        raise AssertionError(
            "unreachable: the last failed attempt raises"
        )  # pragma: no cover

    def _check_not_paused(self, url: str, host: str) -> None:
        """Do not call an endpoint again before the pause it asked for is over."""
        left = self._paused_until.get(_endpoint(url), 0.0) - self._clock()
        if left > 0:
            raise RateLimited(
                f"{host} asked for a pause; about {round(left / 60)} min left"
            )

    def _after_failure(
        self, host: str, attempt: int, error: Exception, pause: int | None = None
    ) -> None:
        """Pause before the next try, or count the failure and raise after the last."""
        if attempt < MAX_TRIES:
            self._sleep(max(BACKOFF_SECONDS * attempt, pause or 0))
            return
        self._failures[host] = self._failures.get(host, 0) + 1
        raise error

    def _wait_for_turn(self, host: str) -> None:
        wait = MIN_INTERVAL[host] - (
            self._clock() - self._last_call.get(host, float("-inf"))
        )
        if wait > 0:
            self._sleep(wait)
        self._last_call[host] = self._clock()


def _endpoint(url: str) -> tuple[str, str]:
    """Host and path up to an id such as ``doi:...``: a search and a lookup differ.

    A server can use up the budget of one kind of call and still answer the other.
    """
    parts = urllib.parse.urlsplit(url)
    return (parts.hostname or "", parts.path.split(":", 1)[0])


def _retry_after(error: urllib.error.HTTPError) -> int | None:
    """The pause in seconds a server asked for; None if absent or not a number."""
    value = error.headers.get("Retry-After") if error.headers is not None else None
    digits = value.strip() if value else ""
    return (
        int(digits)
        if digits.isascii() and digits.isdigit() and len(digits) <= 9
        else None
    )


def _as_os_error(error: Exception) -> Exception:
    """An incomplete read is an HTTPException, not an OSError; name what happened."""
    if isinstance(error, OSError):
        return error
    wrapped = OSError(f"{type(error).__name__}: {error}")
    wrapped.__cause__ = error
    return wrapped
