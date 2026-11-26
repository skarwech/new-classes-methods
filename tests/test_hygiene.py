"""What a public repository must not contain: working wording, personal details, stray
dependency files, leftovers. Every file under the site folder is checked, not only the CSV.
"""

from __future__ import annotations

import getpass
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from explorer.constants import SITE_ROOT
from tests.test_text import EMOJI_OR_PICTOGRAPH
from tests.wording import WORKING_WORDING

pytestmark = pytest.mark.unit

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".toml",
    ".ini",
    ".cfg",
    ".yml",
    ".yaml",
    ".json",
}
TEXT_NAMES = {".gitignore", ".coveragerc"}
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "artifacts",
    "htmlcov",
}
# Files that have to name the forbidden things in order to forbid them.
HOLDS_FORBIDDEN_TEXT = {"test_hygiene.py", "wording.py", "test_text.py"}

ABSOLUTE_PATH = re.compile(
    r"(?:/Users/|/home/|/private/|/var/folders/|[A-Z]:\\Users\\)"
)
# The names of whoever runs the tests: found at run time, so that no name is written down
# in a file that is published.
_ACCOUNT_NAMES = {getpass.getuser(), Path.home().name} - {"", "root", "runner", "user"}
PERSONAL = re.compile(
    "|".join(re.escape(name) for name in sorted(_ACCOUNT_NAMES)) or r"(?!x)x",
    re.IGNORECASE,
)
EMAIL = re.compile(r"[\w.+-]+@(?!example\.(?:org|com|net)\b)[\w-]+\.[\w.-]+")
SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|(?:api[_-]?key|secret|passwd|password)\s*=\s*['\"][^'\"]+['\"]",
    re.IGNORECASE,
)
DEPENDENCY_FILES_THAT_WOULD_OUTRANK_REQUIREMENTS = {
    "uv.lock",
    "Pipfile",
    "Pipfile.lock",
    "environment.yml",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "poetry.lock",
}


def site_files() -> Iterator[Path]:
    for path in sorted(SITE_ROOT.rglob("*")):
        relative = path.relative_to(SITE_ROOT)
        if path.is_file() and not any(part in SKIP_DIRS for part in relative.parts):
            yield path


def text_files() -> list[Path]:
    return [
        path
        for path in site_files()
        if path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES
    ]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def scannable() -> list[Path]:
    return [path for path in text_files() if path.name not in HOLDS_FORBIDDEN_TEXT]


def test_there_are_files_to_check() -> None:
    names = {path.name for path in text_files()}
    assert {"app.py", "README.md", "requirements.txt", "config.toml"} <= names


def test_no_working_wording_in_any_file() -> None:
    hits = [
        f"{path.relative_to(SITE_ROOT)}: {match.group(0)!r}"
        for path in scannable()
        for match in WORKING_WORDING.finditer(read(path))
    ]
    assert not hits, "\n".join(hits[:10])


def test_no_absolute_local_paths_or_personal_details() -> None:
    hits = []
    for path in text_files():
        if path.name == "test_hygiene.py":
            continue
        text = read(path)
        for pattern in (ABSOLUTE_PATH, PERSONAL, EMAIL):
            hits += [
                f"{path.relative_to(SITE_ROOT)}: {match.group(0)!r}"
                for match in pattern.finditer(text)
            ]
    assert not hits, "\n".join(hits[:10])


def test_no_secrets() -> None:
    hits = [
        f"{path.relative_to(SITE_ROOT)}: {match.group(0)[:30]!r}"
        for path in text_files()
        if path.name != "test_hygiene.py"
        for match in SECRET.finditer(read(path))
    ]
    assert not hits, "\n".join(hits)


def test_no_emoji_in_source_or_documents() -> None:
    hits = [
        str(path.relative_to(SITE_ROOT))
        for path in text_files()
        if path.name not in HOLDS_FORBIDDEN_TEXT
        and EMOJI_OR_PICTOGRAPH.search(read(path))
    ]
    assert not hits, hits


def test_requirements_txt_is_the_only_dependency_file() -> None:
    present = {path.name for path in site_files()}
    assert "requirements.txt" in present
    assert not present & DEPENDENCY_FILES_THAT_WOULD_OUTRANK_REQUIREMENTS


def test_requirements_pin_exactly_the_two_runtime_packages() -> None:
    lines = [
        line.strip()
        for line in read(SITE_ROOT / "requirements.txt").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert lines == ["streamlit==1.67.0", "streamlit-arborist==0.4.1"]


def test_development_tools_are_in_a_differently_named_file() -> None:
    text = read(SITE_ROOT / "requirements-dev.txt")
    assert "-r requirements.txt" in text
    for tool in (
        "pytest",
        "pytest-cov",
        "playwright",
        "black",
        "isort",
        "ruff",
        "bandit",
    ):
        assert re.search(rf"^{tool}==", text, re.MULTILINE), tool


def test_the_data_folder_holds_only_the_methods_and_their_abstracts() -> None:
    names = sorted(path.name for path in (SITE_ROOT / "data").iterdir())
    assert names == ["abstracts.csv", "methods_public.csv"]


def test_gitignore_keeps_caches_environments_and_test_output_out() -> None:
    ignored = read(SITE_ROOT / ".gitignore")
    for entry in (".venv/", "__pycache__/", ".pytest_cache/", ".coverage", "htmlcov/"):
        assert entry in ignored, entry
    assert "tests/e2e/artifacts/" in ignored


def test_application_code_does_not_print() -> None:
    offenders = [
        str(path.relative_to(SITE_ROOT))
        for path in [
            SITE_ROOT / "app.py",
            *sorted((SITE_ROOT / "explorer").glob("*.py")),
        ]
        if re.search(r"^\s*print\(", read(path), re.MULTILINE)
    ]
    assert not offenders, offenders


def test_the_readme_documents_the_commands_that_exist() -> None:
    readme = read(SITE_ROOT / "README.md")
    for command in (
        "streamlit run app.py",
        "pip install -r requirements.txt",
        "pip install -r requirements-dev.txt",
        "playwright install chromium",
        "pytest -m e2e",
        "ruff check",
        "bandit",
        "?m=",
        "tools/fetch_abstracts.py",
        "--refresh",
    ):
        assert command in readme, command


def test_every_python_module_has_a_docstring() -> None:
    import ast

    missing = [
        str(path.relative_to(SITE_ROOT))
        for path in text_files()
        if path.suffix == ".py"
        and path.name != "__init__.py"
        and ast.get_docstring(ast.parse(read(path))) is None
    ]
    assert not missing, missing


@pytest.mark.parametrize(
    "name",
    [
        "data/.abstracts-k3j2h1.tmp",  # left by an interrupted write
        "data/abstracts.csv.new",  # the side file when abstracts.csv could not be updated
        ".coverage.host.1234",
        ".env",
        ".env.local",
    ],
)
def test_git_ignores_files_that_must_never_be_added(name: str) -> None:
    import shutil
    import subprocess

    git = shutil.which("git")
    if git is None or not (SITE_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    result = subprocess.run(  # noqa: S603 - fixed arguments
        [git, "check-ignore", "-q", name],
        cwd=SITE_ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"{name} is not ignored by .gitignore"
