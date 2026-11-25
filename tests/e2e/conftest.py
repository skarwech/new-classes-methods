"""Browser tests: start the app, drive it with Chromium through Playwright.

Run with ``pytest -m e2e``. Set ``E2E_BASE_URL`` to test a server that is already running
(the run-counter checks are then skipped, since only the instrumented launcher shows it).
"""

from __future__ import annotations

import glob
import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="install requirements-dev.txt")

from playwright.sync_api import Browser, Page, sync_playwright

SITE_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = Path(__file__).resolve().parent / "instrumented_app.py"
CARDS_APP = Path(__file__).resolve().parent / "all_cards_app.py"
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_healthy(base: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(  # noqa: S310 - our own http://127.0.0.1 address
                f"{base}/_stcore/health", timeout=2
            ) as reply:
                if reply.read().strip() == b"ok":
                    return
        except OSError:
            time.sleep(0.4)
    raise RuntimeError(f"the app did not become healthy at {base}")


def _cached_chromium() -> str | None:
    """A Chromium that Playwright downloaded earlier, whatever its revision."""
    roots = (
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""),
        os.path.expanduser("~/Library/Caches/ms-playwright"),
        os.path.expanduser("~/.cache/ms-playwright"),
    )
    patterns = (
        "chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell",
        "chromium-*/chrome-linux*/chrome",
    )
    for root in filter(None, roots):
        for pattern in patterns:
            hits = sorted(glob.glob(os.path.join(root, pattern)))
            if hits:
                return hits[-1]
    return None


@contextmanager
def running_app(script: Path, extra_args: tuple[str, ...] = ()) -> Iterator[str]:
    """Serve ``script`` with Streamlit on a free port and yield its address."""
    port = _free_port()
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(script),
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--server.fileWatcherType",
        "none",
        "--browser.gatherUsageStats",
        "false",
        *extra_args,
    ]
    server = subprocess.Popen(  # noqa: S603 - fixed argument list, no shell
        command, cwd=SITE_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_until_healthy(base)
        yield base
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    external = os.environ.get("E2E_BASE_URL")
    if external:
        yield external.rstrip("/")
        return
    with running_app(LAUNCHER) as base:
        yield base


@pytest.fixture(scope="session")
def cards_url() -> Iterator[str]:
    """A page that shows every card at once (see all_cards_app.py)."""
    with running_app(CARDS_APP) as base:
        yield base


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch(headless=True)
        except Exception:
            path = _cached_chromium()
            if path is None:
                pytest.skip("no Chromium found: run `playwright install chromium`")
            launched = playwright.chromium.launch(executable_path=path, headless=True)
        yield launched
        launched.close()


@pytest.fixture
def page(browser: Browser, base_url: str) -> Iterator[Page]:
    context = browser.new_context(viewport=DESKTOP, accept_downloads=True)
    context.set_default_timeout(15_000)
    opened = context.new_page()
    opened.goto(base_url)
    yield opened
    context.close()


@pytest.fixture
def phone(browser: Browser, base_url: str) -> Iterator[Page]:
    context = browser.new_context(viewport=PHONE, device_scale_factor=2, has_touch=True)
    context.set_default_timeout(15_000)
    opened = context.new_page()
    opened.goto(base_url)
    yield opened
    context.close()


@pytest.fixture
def open_at(browser: Browser, base_url: str) -> Iterator[object]:
    """Open the app at a given address (path and query) in a fresh page."""
    contexts = []

    def _open(query: str = "", viewport: dict | None = None) -> Page:
        context = browser.new_context(viewport=viewport or DESKTOP)
        context.set_default_timeout(15_000)
        contexts.append(context)
        opened = context.new_page()
        opened.goto(f"{base_url}/{query}")
        return opened

    yield _open
    for context in contexts:
        context.close()
