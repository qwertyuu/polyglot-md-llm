# Polyglot PMD

`polyglot-pmd` is a reusable Python implementation of the PMD 0.1 polyglot
Markdown notebook specification in [`spec.md`](spec.md). It parses and validates
plain-text `.pmd` documents, resolves their dependency graph, runs every cell in
an isolated process, and renders a self-contained HTML report.

[`agent-spec.md`](agent-spec.md) is a draft companion protocol for LLM-ready
notebooks. It specifies bounded semantic inspection, atomic cell-level edits,
impact analysis, execution authorization, and machine-verifiable receipts. The
`pmd agent` command implements that protocol.

[`known-issues.md`](known-issues.md) tracks concrete bugs and friction found
by actually building a notebook with this implementation, not by reading the
source — start there before trusting a claim in this README against an edge
case. [`proposals/`](proposals/) holds focused, spec-style design proposals
that address each item in `known-issues.md`.

> PMD cells execute arbitrary code with the privileges of the user running
> `pmd`. Review a document before running, testing, or rendering it.

## Install

From this checkout:

```console
python -m pip install -e ./pmd-impl
pmd check pmd-impl/example.pmd --graph
pmd run pmd-impl/example.pmd --fresh
pmd run pmd-impl/example.pmd --verbose --out-dir pmd-outputs
pmd test pmd-impl/example.pmd
pmd render pmd-impl/example.pmd --to html
```

Once published:

```console
python -m pip install polyglot-pmd
```

Python 3.10 or newer is required. The package depends only on PyYAML and
markdown-it-py. Language interpreters used by a document must also be installed.

## Library API

```python
from pathlib import Path

from pmd_notebook import Runner, load, render_html, validate

document = load("analysis.pmd")
diagnostics = validate(document)
errors = [item for item in diagnostics if not item.startswith("warning:")]
if errors:
    raise ValueError("\n".join(errors))

result = Runner().run(document, fresh=True)
if not result.ok:
    failed = [cell for cell in result.cells if cell.status == "failed"]

page, render_result = render_html(document, result)
Path("analysis.html").write_text(page, encoding="utf-8")
```

The public API exports `parse`, `load`, `validate`, `closure`,
`topological_order`, `graph_lines`, `Runner`, `Cache`, `execute`,
`render_html`, and `lint_inputs`, plus the corresponding result dataclasses.

## Shared library cells

A `role=lib` cell is never executed on its own; its source text is composed
ahead of any `code`/`setup`/`test` cell in the same language that names it via
`uses=` (comma-separated, like `depends-on`):

````markdown
```python {#bot_constants role=lib}
BOT_SIDE = {"6z7257126u1c7bvw": "light"}
```

```python {#bot_roster depends-on=setup uses=bot_constants}
for gid, side in BOT_SIDE.items():
    ...
```
````

This avoids retyping an identical constant table or helper into every cell
that needs it, while keeping process isolation intact — nothing crosses a
process boundary that wasn't already textually composed into that one
process's script. Editing a `lib` cell invalidates the cache of every cell
that `uses` it.

## Rendering with tests

`pmd render file.pmd --to html --with-tests` additionally executes every
`role=test` cell and shows its real pass/fail status in the rendered HTML,
instead of leaving it as an unexecuted "not-run" block. A failing test still
produces a complete HTML file (with a banner) but exits non-zero.

## Linting declared inputs

`pmd check file.pmd --lint-inputs` is an opt-in, warnings-only static scan
that flags path-shaped tokens in cell source that look like data-file paths
but aren't covered by frontmatter `inputs:`, and declared `inputs:` entries
no cell appears to reference. It matches individual tokens (not whole string
literals), unescapes common escape sequences first, and skips a `display.*`
call's `name=` destination-filename argument. It never fails `pmd check`'s
exit code — false positives are still possible from a purely textual
heuristic (e.g. a source-file path mentioned in a prose citation). Tune it
with:

```yaml
lint:
  input_extensions: [".parquet", ".csv", ".json", ".duckdb", ".png"]
  ignore_patterns: ["https?://", "^/tmp/"]
```

## Patching a cell against cached context

`pmd run file.pmd --cell ID --patch -` (or `--patch snippet.py`) resolves
`ID`'s upstream dependency closure exactly like `pmd run --cell ID`, then
executes the patch source instead of `ID`'s own source, with `ID`'s
attributes and resolved upstream `ctx`. The patch run is never cached and
never written back to the document — it's for probing a candidate snippet
against real, already-resolved context without touching the source file.

## Context Bindings

Each cell receives `PMD_CELL_OUT` and `PMD_CTX_FILE`. Built-in engines add these
bindings:

| Engine | Read | Write | Presence check |
| --- | --- | --- | --- |
| Python | `ctx.get("key")` or `ctx.key` | `ctx.set("key", value)` or `ctx.key = value` | `ctx.has("key")` |
| Bash/sh | `ctx_get key` | `ctx_set key 'JSON_VALUE'` | `ctx_has key` |
| PowerShell | `Get-CtxValue key` | `Set-CtxValue key $value` | `Test-CtxValue key` |
| SQL | `ctx_get('key')` | `ctx_set('key', 'JSON_VALUE')` | not provided |

Shell reads print JSON, so a stored string includes JSON quotes. SQL uses an
isolated in-memory SQLite database. Override commands under frontmatter
`engines.<language>.command`; custom engines still receive the two environment
variables but must provide their own context helpers.

Write `.png`, `.jpg`, `.jpeg`, `.svg`, `.csv`, `.md`, or any other attachment
under `PMD_CELL_OUT`. The HTML renderer embeds all files and makes no network
requests. Python also receives `display.markdown`, `display.csv`,
`display.image`, and `display.file` convenience methods.

### Dependency outputs

Every cell receives `PMD_DEP_OUTPUTS`, a JSON object mapping transitive
dependency cell IDs to temporary output directories. Python cells also receive
an `outputs` helper:

```python
chart = outputs.path("make-chart", "chart.png")
all_files = outputs.files("make-chart")
```

Paths are read-only by convention and remain available for the duration of the
run. Cached dependency attachments are reconstructed before downstream cells
start, so tests behave the same with warm and cold caches.

Use `pmd run --out-dir PATH` or `pmd test --out-dir PATH` to retain attachments
after the run. Files are exported under `PATH/<cell-id>/`. Use `--verbose` to
print successful cells' captured stdout and stderr in addition to statuses.

## Caching

Successful dependency results are cached under `PMD_CACHE_DIR`, or
`~/.cache/polyglot-pmd` by default. Keys include source, attributes, engine
command, and the resolved transitive context. `--fresh` bypasses reads. A cell
named by `--cell` always executes; only its dependencies may come from cache.
Context itself remains scoped to one invocation.

External files are not inferable from arbitrary source code. Declare them in
frontmatter so their content hashes participate in every cell's cache key:

```yaml
inputs:
  - data/games.parquet
  - config.json
```

Paths resolve relative to the `.pmd` document. Files and directories are
supported; directory fingerprints include every contained file. Missing
declared inputs fail before any cell executes.

## Portable Engine Commands

Frontmatter engine commands expand environment variables and the
`{document_dir}` placeholder. Relative executable paths also resolve from the
document directory:

```yaml
engines:
  python:
    command: "{document_dir}/.venv/Scripts/python.exe"
```

On POSIX, the corresponding command would normally end in `.venv/bin/python`.
This selects an existing environment; PMD still does not provision packages.

## Optional Workbench

Run `python server.py` and open `http://localhost:8765`. The local workbench is
not installed as part of the Python package.

## Publishing to PyPI

1. Replace package author metadata if desired and choose the final project URL.
2. Run `python -m pip install -e ".[dev]"`.
3. Run `pytest` and `python -m build`.
4. Check artifacts with `python -m twine check dist/*`.
5. Upload to TestPyPI, install-test the wheel, then upload to PyPI.

```console
python -m twine upload --repository testpypi dist/*
python -m twine upload dist/*
```

PDF and `.ipynb` are optional PMD render targets and are intentionally not
implemented. The CLI refuses them clearly instead of silently losing content.

## LLM-ready agent protocol

Discover the machine interface without parsing human help text:

```console
pmd agent capabilities
```

Inspect one cell with its immediate dependencies, consumers, tests, and
adjacent narrative:

```console
echo '{"roots":["summarize"],"upstream_depth":1,"downstream_depth":1,"include_tests":true,"include_source":true,"include_narrative":"adjacent"}' |
  pmd agent inspect example.pmd --request -
```

Apply edits using the exact document and cell-source digests returned by
inspection. Transactions are validated and written atomically:

```console
pmd agent apply example.pmd --request change.json
```

The apply response contains an opaque `change_token` and a
`recommended_verification` request. Planning never executes code:

```console
pmd agent verify example.pmd --request verify.json
```

Execution requires an explicit host authorization signal:

```console
pmd agent verify example.pmd --request verify.json --allow-execution
```

Every agent command writes exactly one JSON object to stdout. Notebook prose,
source, streams, and outputs are labeled or treated as untrusted content.
Filesystem and network restrictions are reported as unenforceable by the local
subprocess runner rather than being presented as sandboxed.

