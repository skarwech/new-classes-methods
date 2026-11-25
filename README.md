# Handling New Classes in Production: methods collection

A read-only website that shows a collection of methods for handling classes a model did
not see in training. The methods are shown as a collapsible tree: four paradigm families
(Unknown Rejection, Class Discovery, Model Integration, Stream Adaptation) and a group of
pipeline references. Click a method to see its reference, a link to the paper, a link to
the code and how far the reference has been checked. A sidebar searches (ignoring accents
and case) and filters by family, code availability, reference check and year, and
downloads the filtered rows as CSV.

It is a single Streamlit page that reads `data/methods_public.csv` and deploys from a
GitHub repository to Streamlit Community Cloud.

## Run it locally

Streamlit 1.67 needs Python 3.11 or newer.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Run it from this folder: the folder is the repository root, and Streamlit reads
`.streamlit/config.toml` from it.

A link ending in `?m=<id>` opens that method with its folders expanded, for example
`http://localhost:8501/?m=4`.

## What is in the repository

```
app.py                      page layout and wiring
explorer/                   the logic, as small modules that are easy to test
  data.py                   read and validate the CSV
  filters.py, textfold.py   search and filters, accent folding
  tree.py                   build the tree, labels, what to open when it is mounted
  selection.py              which method is selected
  card.py, links.py         text of the card, safe links
  constants.py              column names, code and check labels, layout numbers
  text.py                   title, how-to-read text, messages
  export.py                 CSV download
data/methods_public.csv     the data (the only data file)
.streamlit/config.toml      theme and one server setting (see below)
requirements.txt            the two pinned runtime dependencies
tests/                      unit, whole-script and browser tests
```

`requirements-dev.txt`, `pytest.ini`, `ruff.toml` and `.coveragerc` are for development.
Keep `requirements.txt` as the only dependency file: Community Cloud picks the first one
it finds, so a `pyproject.toml`, `Pipfile`, `environment.yml` or `uv.lock` here would
take precedence or cause confusion.

## The data

`data/methods_public.csv` has one row per method and 17 text columns: `id`, `tree_family`,
`tree_section`, `tree_type`, `method`, `year`, `authors_surnames`, `authors_complete`,
`title`, `venue`, `doi`, `arxiv`, `paper_url`, `code_url`, `code_type`, `code_alt`,
`check`. The tree is built from `tree_family`, `tree_section` and `tree_type`, in the order
of first appearance in the file. `code_alt` holds `type|URL` entries separated by ` ; `.

The file is checked when the app starts. If a column is missing, an id is repeated, a link
is not `http` or `https`, or a value is outside its vocabulary, the page shows what is
wrong and stops, instead of showing something misleading.

The working file and the script that writes the public CSV from it belong to the author and
live outside this repository.

Text cells (`method`, `authors_surnames`, `title`, `venue`) may not contain line breaks,
control characters, web addresses, `@` signs or `:name:` patterns: the markdown renderer
would turn them into links, e-mail links or emoji. Ids may use only letters, digits, `.`,
`_` and `-`, up to 32 characters. The page says which row and column break a rule.

To update: regenerate the public CSV from the working file, replace
`data/methods_public.csv`, commit and push. Do not edit the public file by hand. The app
reads the file again when it changes (its modification time is part of the cache key), so
no restart is needed. The tests quote counts of the shipped data (170 methods, 63/31/23/43/10
per family, and so on): after a change, run `pytest` and update the numbers it flags,
starting with `tests/test_public_csv.py`. The app itself never hard-codes a count.

## Deploy to Streamlit Community Cloud

1. Push this folder, as the root of its own repository, to GitHub. Everything in the
   repository is readable by visitors, so keep only this folder's files in it.
2. On share.streamlit.io choose Create app, then "Yup, I have an app", then pick the
   repository, the branch and `app.py`.
3. Optionally choose a subdomain (App URL).
4. In Advanced settings, set the Python version to 3.11 or newer (the dropdown defaults to
   3.12; 3.13 was used for development). No secrets are needed.
5. Deploy. It takes a few minutes.

Afterwards a code push shows immediately and a dependency change takes a few minutes. An
app with no traffic for 12 hours goes to sleep; the first visitor after that waits for a
restart. Open the deployed address once in a private window to check it.

## How it works

- **Labels.** Every folder shows its count and every method reads `Name (year)`. A name that
  already ends in a year, such as `Ledoit & Wolf (2004)`, is shown as it is.
- **Selection.** Clicking a method sends it to the page through the tree's `on_change`
  callback; that is the only thing that changes the selection after the tree is mounted. The
  tree's `selection` and `initial_open_state` are set once per mount and then held constant:
  the component re-applies its `selection` whenever that value changes, which fires its
  selection event again and can start a loop of reruns. The widget key is derived from the
  filters, so changing a filter mounts a fresh tree, with every remaining folder open. The
  selected method's folders are always opened at mount, because the tree can only highlight
  a method that is visible.
- **Address.** `?m=<id>` always mirrors the selection. An unknown or malformed id is
  ignored and removed. Other parameters are left alone. A selection hidden by a filter stays
  in the address and comes back when the filter is cleared.
- **Server setting.** `.streamlit/config.toml` raises `global.minCachedMessageSize`. The
  tree's data is about 14 kB when nothing is filtered, above Streamlit's default limit of
  10 kB for replacing a repeated message by a hash. After many quick filter changes the
  browser could miss that hash and the page stopped with "Connection error: Cached
  ForwardMsg MISS". Under a stress test, 6 of 30 sessions failed that way with the default
  and none of 110 with the raised limit.
- **Text only.** No emoji, icons or images, and no icons passed to the tree (plain-text icons
  raise an exception in the component).
- **Untrusted text.** Everything from the CSV is escaped before it goes into markdown. The
  loader also refuses what escaping cannot protect (see "The data"). Links are accepted only
  if they are `http` or `https`, and are percent-encoded where they could end a markdown
  link early.
- **Quick clicks.** A click can reach a tree that has already been replaced (a search term
  typed, then a row clicked before the new tree arrived). The click is remembered, and the
  next run mounts a fresh tree under a new widget key so that it shows the selection.

If the tree component ever breaks on a new Streamlit version, nested `st.expander` blocks
(about 240 for 170 methods) or nested HTML `<details>` are fallbacks that need no extra
dependency.

## Tests and checks

```bash
pip install -r requirements-dev.txt
playwright install chromium      # once, for the browser tests

pytest                           # unit and whole-script tests
pytest --cov                     # the same, with line and branch coverage
pytest -m e2e                    # browser tests: start the app and drive Chromium

ruff check . && black --check . && isort --check --profile black .
bandit -q -r explorer app.py
```

The browser tests are the only ones that click the real tree. They start the app
themselves, through `tests/e2e/instrumented_app.py`, which wraps `app.py` and shows how
many times the script has run, so that a click can be checked to cause exactly one run and
to settle. Set `E2E_BASE_URL` to run them against a server that is already running.

## Known limits

- On a phone, a few of the longest labels are cut off by the tree component, which cannot
  wrap them. The indent is 16 px to leave as much room as possible; shorten the labels in
  the CSV if that matters.
- Folders are told apart from methods by their count and indentation only, since no icons
  are used.
- Keyboard: Tab enters the tree and cannot leave it again (a property of the tree
  component, streamlit-arborist 0.4.1). Arrow keys move through the rows and Space selects
  one. To reach the card by keyboard, press Shift+Tab from the top of the page, which goes
  to the end of the page first. The fallbacks listed above avoid the trap.
- Every selection adds an entry to the browser history, and moving back or forward between
  two `?m=` addresses within one session does not change the selection; reload the page to
  follow an address.
- Opening the downloaded CSV directly in a spreadsheet program can reformat values such as
  arXiv ids that end in 0 (1706.02690 becomes 1706.0269); import those columns as text.
