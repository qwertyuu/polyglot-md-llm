# Polyglot PMD

[![CI](https://github.com/qwertyuu/polyglot-md-llm/actions/workflows/ci.yml/badge.svg)](https://github.com/qwertyuu/polyglot-md-llm/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/polyglot-pmd)](https://pypi.org/project/polyglot-pmd/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB)](https://www.python.org/)
[![MIT license](https://img.shields.io/badge/license-MIT-2f855a)](https://github.com/qwertyuu/polyglot-md-llm/blob/main/LICENSE)

Plain-text notebooks that stay valid Markdown.

`polyglot-pmd` parses and validates `.pmd` documents, resolves their dependency
graph, runs each cell in an isolated process, and renders a self-contained HTML
report. A notebook can mix Python, shell, PowerShell, and SQL without hiding its
execution model inside a binary file format.

## Quickstart

With [uv](https://docs.astral.sh/uv/), no environment setup or package install is
needed. `uvx` runs PMD in an isolated environment and caches it for later calls:

```console
git clone https://github.com/qwertyuu/polyglot-md-llm.git
cd polyglot-md-llm
uvx --from polyglot-pmd pmd check examples/basic.pmd --graph
uvx --from polyglot-pmd pmd run examples/basic.pmd --fresh --verbose
uvx --from polyglot-pmd pmd test examples/basic.pmd --fresh
uvx --from polyglot-pmd pmd render examples/basic.pmd --to html --out example.html
```

Open `example.html` to see the source, dependency graph, captured streams, and
rich outputs in one portable report. To create a standalone project instead:

```console
mkdir my-analysis
cd my-analysis
uv tool install polyglot-pmd
pmd init .
pmd workbench .
```

`uv tool install` keeps `pmd` on your `PATH`. Run `uv tool update-shell` if uv
reports that its tool directory is not currently on `PATH`.

> PMD cells execute arbitrary code with the privileges of the user running
> `pmd`. Review a document before running, testing, or rendering it.

## Why PMD

- **Readable diffs:** notebooks are ordinary Markdown with fenced code cells.
- **Explicit dataflow:** ordering, JSON context, files, and shared source use
  separate mechanisms rather than hidden process state.
- **Polyglot execution:** built-in engines cover Python, shell, PowerShell, and
  in-memory SQLite.
- **Reproducible runs:** dependency-aware caching includes source, interpreters,
  context, and declared input files.
- **Agent-safe editing primitives:** bounded inspection, digest-protected edits,
  explicit execution authorization, and verification receipts are built in.

The PMD 0.1 format is specified in [`docs/spec.md`](https://github.com/qwertyuu/polyglot-md-llm/blob/main/docs/spec.md).

[`docs/agent-protocol.md`](https://github.com/qwertyuu/polyglot-md-llm/blob/main/docs/agent-protocol.md) is a draft companion protocol for LLM-ready
notebooks. It specifies bounded semantic inspection, atomic cell-level edits,
impact analysis, execution authorization, and machine-verifiable receipts. The
`pmd agent` command implements that protocol.

[`docs/known-issues.md`](https://github.com/qwertyuu/polyglot-md-llm/blob/main/docs/known-issues.md) tracks concrete bugs and friction found
by actually building a notebook with this implementation, not by reading the
source. Start there before trusting a claim in this README against an edge
case. [`proposals/`](https://github.com/qwertyuu/polyglot-md-llm/tree/main/proposals/) holds focused, spec-style design proposals
that address each item in `docs/known-issues.md`.

## Five-minute mental model

Each executable cell runs as an isolated operating-system process. Nothing in a
Python variable, import cache, or working memory crosses a cell boundary.
There are four deliberately different ways cells relate:

| Mechanism | What moves | Why it exists |
| --- | --- | --- |
| `depends-on` | execution ordering and visibility | makes an upstream result available before a consumer starts |
| `ctx` | JSON values | passes small, portable values such as settings, lists, and summaries |
| outputs | files | passes plots, tables, models, and other non-JSON artifacts |
| `uses` | source text | composes a shared `role=lib` helper into an isolated process |

This complete example uses all four. `common` is source composition, `prepare`
establishes order and sends JSON, `plot` writes a file, and `review` consumes the
file through the dependency-output helper:

````markdown
```python {#common role=lib}
from pathlib import Path
def mean(values): return sum(values) / len(values)
```

```python {#prepare role=setup uses=common independent=true}
ctx.values = [2, 4, 8]
ctx.average = mean(ctx.values)
```

```python {#plot depends-on=prepare uses=common}
import matplotlib.pyplot as plt
fig, ax = plt.subplots(); ax.plot(ctx.values)
display.figure(fig, "trend.png")
```

```python {#review depends-on=plot}
assert outputs.path("plot", "trend.png").is_file()
print(ctx.average)
```
````

Use a bare fence for the simple path; PMD assigns an ID automatically and uses
normal notebook order. Add IDs, dependencies, context, artifacts, and `uses`
only when the notebook needs them.

`role=setup` is the convention for the first executable cell: resolve project
settings, create directories, and put JSON configuration in `ctx`. For Python,
`project_root`/`project_dir` resolves to the nearest `pmd.yaml`, `pyproject.toml`,
or Git root, and `output_path("tables/result.csv")` creates a safe output path.
Use `display.figure(fig, "plot.png")` to save and register a Matplotlib figure
in one call. Any file already written under `PMD_CELL_OUT` is collected
automatically, so it does not need a `display.image()` call.

## Installation

Run any PMD command without installing it:

```console
uvx --from polyglot-pmd pmd --version
uvx --from polyglot-pmd pmd check examples/basic.pmd --graph
```

Or install the command persistently:

```console
uv tool install polyglot-pmd
pmd --version
```

For development from this checkout:

```console
python -m pip install -e ".[dev]"
pmd check examples/basic.pmd --graph
pmd run examples/basic.pmd --fresh
pmd run examples/basic.pmd --verbose --out-dir pmd-outputs
pmd test examples/basic.pmd
pmd render examples/basic.pmd --to html
pmd render examples/basic.pmd --to text
```

From PyPI:

```console
python -m pip install polyglot-pmd
```

Python 3.10 or newer is required. The package depends only on PyYAML and
markdown-it-py. Language interpreters used by a document must also be installed.

More complete walkthroughs live in [`examples/`](https://github.com/qwertyuu/polyglot-md-llm/tree/main/examples/). The
[`examples/v0.6/`](https://github.com/qwertyuu/polyglot-md-llm/tree/main/examples/v0.6/) feature tour covers typed outputs, sweeps,
document tests, agent failures, verification receipts, and attestations.

## Document and composition workflows

PMD 0.6 adds reader-visible validation and callable contracts:

```console
pmd render report.pmd --to text
pmd render report.pmd --to html --hide-graph --hide-source
pmd run report.pmd --set tuiles.canada=1600
pmd run report.pmd --sweep tuiles.canada=1400,1568,1800
pmd run report.pmd --compare-with RUN_ID
pmd call report.pmd --input '{"tuiles":{"canada":1600}}' --output totaux
```

Use `stale-after=30d` on measurement cells. A Python
`role=test test-of=document` cell can assert over `rendered.text`. Typed outputs
use `produces=totaux:schema#totals` with JSON Schema definitions under
frontmatter `schemas`. Frontmatter `capabilities.network` and
`capabilities.ssh` declare external hosts for static inspection.

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
never written back to the document. It is for probing a candidate snippet
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
`display.csv` accepts CSV text or a list of dictionaries; ambiguous values
raise `TypeError` instead of being stringified silently.

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
command, resolved interpreter identity/version, and the resolved transitive
context. `--fresh` bypasses reads. A cell
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

For portable projects, run `pmd` from the project's virtual environment, or
commit a project-level `pmd.yaml` with an interpreter command. `pmd init`
creates both that configuration and a minimal `notebook.pmd`; `{project_dir}`
in the command expands to the project root. Its platform-native template uses
`.venv/Scripts/python.exe` on Windows and `.venv/bin/python` on macOS/Linux.
Initialization selects that environment but does not create it.

## Formatting, modules, and CI

`pmd fmt notebook.pmd` normalizes frontmatter, fence attributes, and the final
newline. `pmd extract notebook.pmd CELL --out src/helper.py` writes a cell to a
normal source file, while `pmd inline src/helper.py --cell helper` prints a PMD
fence for it. `pmd agent edit notebook.pmd --cell CELL --from src/helper.py`
performs the same replacement through the agent transaction path, retaining both
document-revision and source-digest preconditions.

Declare notebook-wide cache inputs in frontmatter or narrowly on one cell:

```markdown
```python {#fit inputs=data/derived.csv,config/model.json}
...
```
```

`pmd check notebook.pmd --lint-inputs` remains advisory. For CI, use
`--strict-inputs`: high-confidence undeclared literal inputs fail the command;
lower-confidence stale declarations are reported as advisories. `pmd audit-deps
notebook.pmd` finds local imported source modules and prints candidate
frontmatter inputs. The rendered HTML also annotates direct local
`from module import function` provenance.

## Optional Workbench

Start the local browser workbench with the installed CLI:

```console
pmd workbench .
```

Open `http://127.0.0.1:8765`. The workbench lists and edits `.pmd` files in the
selected directory, supports validation, runs a cell or a full notebook, and
shows outputs inline. It binds only to loopback by default. Use `--port PORT`
or `--host HOST` when needed; exposing it beyond your machine is unsafe because
it can edit and execute notebook code.

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

## Contributing

Bug reports, focused proposals, documentation improvements, and pull requests
are welcome. Start with [`CONTRIBUTING.md`](https://github.com/qwertyuu/polyglot-md-llm/blob/main/CONTRIBUTING.md), review the
[`SECURITY.md`](https://github.com/qwertyuu/polyglot-md-llm/blob/main/SECURITY.md) policy for vulnerabilities, and see
[`proposals/`](https://github.com/qwertyuu/polyglot-md-llm/tree/main/proposals/) for the project's design process.

## LLM-ready agent protocol

The project ships an agent skill at
[`skills/polyglot-pmd/SKILL.md`](https://github.com/qwertyuu/polyglot-md-llm/blob/main/skills/polyglot-pmd/SKILL.md). It is also
included in wheels as `pmd_notebook/skills/polyglot-pmd/SKILL.md`. The skill
teaches agents to discover the installed version and protocol before acting,
then use digest-protected semantic edits and scoped verification. Its release
and capability snapshot are covered by tests, so adding a public agent feature
requires updating the shipped workflow in the same change.

Discover the machine interface without parsing human help text:

```console
pmd agent capabilities
```

Inspect one cell with its immediate dependencies, consumers, tests, and
adjacent narrative:

```console
echo '{"roots":["summarize"],"upstream_depth":1,"downstream_depth":1,"include_tests":true,"include_source":true,"include_narrative":"adjacent"}' |
  pmd agent inspect examples/basic.pmd --request -
```

Apply edits using the exact document and cell-source digests returned by
inspection. Transactions are validated and written atomically:

```console
pmd agent apply examples/basic.pmd --request change.json
```

The apply response contains an opaque `change_token` and a
`recommended_verification` request. Planning never executes code:

```console
pmd agent verify examples/basic.pmd --request verify.json
```

Execution requires an explicit host authorization signal:

```console
pmd agent verify examples/basic.pmd --request verify.json --allow-execution
pmd agent inspect examples/basic.pmd --include-rendered --allow-execution
pmd agent run examples/basic.pmd --stream --allow-execution
pmd attest examples/basic.pmd --receipt receipt.json
```

Non-streaming agent commands write exactly one JSON object to stdout;
`agent run --stream` writes NDJSON events. Notebook prose, source, streams, and
outputs are labeled or treated as untrusted content.
Filesystem and network restrictions are reported as unenforceable by the local
subprocess runner rather than being presented as sandboxed.
