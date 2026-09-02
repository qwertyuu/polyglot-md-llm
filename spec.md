# PMD — Polyglot Markdown Notebook Format

**Specification — Draft v0.1**
**Status:** Draft. No reference implementation exists yet. This document is the contract a conforming implementation must satisfy; it does not prescribe implementation language, architecture, or internal storage.

**File extension:** `.pmd`
**Suggested MIME type:** `text/vnd.pmd+markdown` (unregistered; implementations may treat `.pmd` files as `text/markdown` for maximum tool compatibility).

## 0. Conformance language

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** in this document are to be interpreted as described in RFC 2119. Sections marked *(non-normative)* are explanatory or advisory and impose no conformance requirement.

---

## 1. Motivation

`.ipynb` stores a notebook as a single JSON object: source code as arrays of escaped strings, outputs (including base64-encoded binary blobs) inline in the same structure as the source, and no explicit model of dependency between cells. This makes the format expensive to edit programmatically (every edit is a JSON-surgery problem, not a text-editing problem), noisy to diff, and prone to the "hidden state" problem — a notebook that runs top-to-bottom can produce different results than what is currently displayed, because nothing prevents cells from being executed out of order.

PMD is a plain-text, polyglot, dependency-aware notebook source format designed to be:

- **Editable as text** — by a human, an editor, or a language model — with no serialization ceremony.
- **Diff-friendly** — a one-line change produces a one-line diff.
- **Polyglot** — a single document can mix bash, PowerShell, Python, SQL, or any other language, cell by cell.
- **Explicit about state** — every cell's dependencies are declared or governed by a simple default rule; nothing is hidden.
- **Independently runnable, debuggable, and testable** — any single cell can be executed, re-executed, or tested in isolation.
- **Capable of producing a self-contained artifact** — a single file bundling narrative, code, and captured results for viewing or sharing — without that artifact being the editable source.

PMD is not a new filesystem, not a new markup language, and not a replacement for Jupyter. It is a source format plus an execution contract that a runner implements.

---

## 2. Design goals and non-goals

### 2.1 Goals

1. A `.pmd` file **MUST** remain valid CommonMark. Any Markdown renderer that ignores unknown info-string content must still render the document without breaking code-fence detection.
2. Cell identity **MUST** be stable and independent of position — moving a cell in the file must not change its identity.
3. Dependencies between cells **MUST** be either explicit or governed by one unambiguous default rule (§5.2) — never inferred by magic that the author cannot inspect.
4. Cross-language state passing **MUST** go through a single, narrow, language-agnostic contract (§6) — no shared kernel, no shared memory.
5. A conforming runner **MUST** be able to execute exactly one cell, in isolation, given only the cached or freshly-computed state of its declared dependencies (§9.1).
6. A conforming runner **MUST** be able to produce one self-contained rendered artifact per document (§11).

### 2.2 Non-goals

- PMD does not define a package-management or environment-provisioning mechanism. Declaring *which* Python or which packages a cell needs is implementation-defined (see §15, open extension points).
- PMD does not mandate a sandboxing or security model. Executing a `.pmd` file executes arbitrary code, in multiple languages, on the host; see §12.
- PMD does not define reactive re-execution (à la marimo/Observable) as a core requirement. An implementation MAY add it as an extension; the core contract only requires deterministic batch execution.
- PMD does not replace `.ipynb`. Export to `.ipynb` is an optional render target (§11.3), not the working format.

---

## 3. Terminology

| Term | Meaning |
|---|---|
| **Document** | A single `.pmd` file. |
| **Cell** | A fenced code block carrying a `#id` attribute. The unit of execution. |
| **Narrative** | Any Markdown content between cells. Never executed. |
| **Engine** | The interpreter/process a given language is dispatched to (e.g. `bash`, `python`, `pwsh`). |
| **Run** | One invocation of the runner against a document (`pmd run`, `pmd test`, or `pmd render`), producing a fresh dependency resolution and its own run-scoped context store. |
| **Run context (`ctx`)** | The key-value store cells use to exchange values across languages during a single run. |
| **Runner** | The conforming implementation of this spec: parser + dependency resolver + execution engine + renderer. |

---

## 4. File format

### 4.1 Base syntax

A `.pmd` document is CommonMark. Cells are ordinary fenced code blocks whose info string carries a **cell-attribute block**. Everything outside a cell is narrative and is never executed.

### 4.2 Document frontmatter *(optional)*

A document **MAY** begin with a YAML frontmatter block:

```yaml
---
pmd: "0.1"
title: "Quarterly ingest report"
engines:
  bash:
    command: "bash"
  python:
    command: "python3"
  pwsh:
    command: "pwsh -NoLogo -NoProfile -Command -"
ctx:
  backend: "json"          # implementation-defined; "json" | "sqlite" | other
timeout_default: "60s"
---
```

- `pmd` — spec version this document targets. Runners **SHOULD** warn on a version they don't recognize rather than silently misparsing.
- `engines` — maps a language identifier (as used in fence info strings) to a launch command. A runner **MUST** provide sensible built-in defaults for common languages (`bash`, `sh`, `python`, `pwsh`/`powershell`, `sql`) and **MAY** let frontmatter override them.
- `ctx.backend` — implementation-defined hint for how the run context is persisted (§6). Purely advisory; a runner **MAY** ignore it and use its own default.
- `timeout_default` — default per-cell timeout when a cell doesn't specify its own (§4.5).

If `engines` references a language absent from both the frontmatter and the runner's built-ins, `pmd check` **MUST** fail with an error naming the missing engine (§10.1).

### 4.3 Cell grammar

```
code-fence     := "```" language SP? cell-attrs? NEWLINE body "```"
cell-attrs     := "{" attr (SP+ attr)* "}"
attr           := id-shorthand | key-value
id-shorthand   := "#" cell-id
key-value      := attr-key "=" attr-value
attr-key       := "role" | "depends-on" | "independent" | "test-of" | "uses"
                | "timeout" | "env" | "expect-exit-code" | "skip" | "tags"
attr-value     := bare-token | quoted-string
cell-id        := [a-z][a-z0-9_-]{0,63}
```

A fenced code block with **no** `#id` attribute is **not** a cell — it is an ordinary, non-executed illustrative code sample, exactly as in plain Markdown. This lets a `.pmd` document show non-executed example snippets without ambiguity.

Example:

````markdown
```python {#compute depends-on=fetch role=code timeout=30s}
import json
data = json.load(open("data.json"))
```
````

### 4.4 Cell attributes reference

| Attribute | Applies to | Type | Default | Meaning |
|---|---|---|---|---|
| `#id` | all cells | string, unique in document | *(required)* | Stable identifier. Referenced by `depends-on`, `test-of`, and `uses`. |
| `role` | all cells | `code` \| `setup` \| `test` \| `scratch` \| `lib` | `code` | Execution role (§5.1, §8). |
| `depends-on` | `code`, `setup`, `test` | comma-separated list of ids | *(implicit, §5.2)* | Explicit upstream dependencies. |
| `independent` | `code`, `setup` | boolean | `false` | Disables the implicit sequential dependency described in §5.2. |
| `test-of` | `test` only | single id | *(required for `role=test`)* | The cell this test validates (§8.1). |
| `uses` | `code`, `setup`, `test` | comma-separated list of `role=lib` ids, same language | none | Textually composes the named `lib` cells' source ahead of this cell's own source (§4.6). |
| `timeout` | `code`, `setup`, `test` | duration (`30s`, `2m`) | document `timeout_default` or `60s` | Wall-clock limit before the runner kills the process. |
| `env` | `code`, `setup`, `test` | comma list of `KEY` or `KEY=VALUE` | none | Extra environment variables passed to the process. |
| `expect-exit-code` | `code`, `setup`, `test` | integer | `0` | Exit code treated as success. |
| `skip` | all | boolean | `false` | Cell is excluded from `run`, `test`, and `render`. |
| `tags` | all | comma list | none | Free-form labels for filtering (`pmd run --tag X`). |

Unknown attributes **MUST** cause `pmd check` to fail (fail loud, not silently ignore — this is what makes the format safe for an LLM to edit without a human proofreading every change).

### 4.5 Cell IDs

- Must match `[a-z][a-z0-9_-]{0,63}`.
- Must be unique within a document.
- Must never be reused for a semantically different cell across edits if the document is meant to preserve cache hits (§5.5) — this is a convention, not a hard requirement.

### 4.6 Roles

| Role | Meaning |
|---|---|
| `code` | A normal executable step. Participates in `run` and `render`. |
| `setup` | Same as `code`, but semantically marks fixtures/preamble (e.g. imports, test doubles). Purely documentary — the runner treats it identically to `code`. |
| `test` | An assertion cell. Participates only in `pmd test`, never in `pmd run` / `pmd render` unless something else explicitly depends on it. |
| `scratch` | Never executed by `run`, `test`, or `render`. A place for a human or an agent to leave throwaway exploration without it affecting any pipeline. Runners **MAY** offer an explicit `pmd run --include-scratch` for interactive use. |
| `lib` | Never executed on its own and excluded from `run`/`test`/`render` roots and `--cell` targets, exactly like `scratch`. Its source text **MUST** be textually prepended — in `uses` order — to the source of any `code`/`setup`/`test` cell in the same language that names it via `uses` (§4.4), immediately after that cell's language binding preamble and before the using cell's own source. Purely a compile-time source-composition step: it does not run as a separate process, produces no `ctx`/output of its own, and **MUST NOT** declare `depends-on`, `independent`, or `test-of`. Editing a `lib` cell is a cache-invalidating change for every cell that `uses` it (§5.5), since the composed source is the effective source for caching purposes. |

### 4.7 Degradation in plain Markdown viewers *(non-normative)*

Because the attribute block lives inside the fence info string, a Markdown renderer that doesn't understand it will typically display the literal `{...}` text next to the language name, or fail to detect the language for syntax highlighting. This is a known, accepted cosmetic trade-off in exchange for the file remaining valid, parseable CommonMark with zero escaping. An implementation **MAY** ship a "strip" mode that emits a display-only `.md` copy with attributes removed, for pasting into contexts that don't tolerate them.

---

## 5. Execution model

### 5.1 Cells vs. narrative

Only fenced blocks carrying a `#id` are cells. Everything else — headings, paragraphs, images, plain (unattributed) code samples — is narrative and is copied into the rendered output verbatim but never executed.

### 5.2 Dependency graph construction

- Nodes: every cell with `role` in `{code, setup}`, plus every `test` cell (test cells form their own sub-graph rooted at their `test-of` target — see §8).
- Edges: from `depends-on`.
- **Default rule:** if a `code`/`setup` cell declares no `depends-on` and is not marked `independent: true`, it **MUST** be treated as depending on the nearest preceding `code`/`setup` cell in document order (skipping `scratch` and `test` cells). This preserves the familiar "reads top to bottom" mental model while remaining fully explicit and inspectable — an author or an agent can always see the resolved graph via `pmd check --graph`.
- A cell marked `independent: true` with no `depends-on` has no upstream dependency and **MUST** be eligible to run first, in parallel with any other independent cell, at the runner's discretion.

### 5.3 Execution order

The runner **MUST** compute a topological order over the dependency graph. Ties (cells with no ordering constraint between them) **MUST** be broken by document order, so that execution order is deterministic given a fixed document.

### 5.4 Process isolation

Each cell **MUST** run in its own OS process, in the engine declared for its language (§4.2). Cells **MUST NOT** share language-level memory (no shared Python interpreter, no shared PowerShell session) across cells. Any state that must cross a cell boundary — same language or not — **MUST** go through the run context (§6) or the filesystem.

A runner **MUST** transmit a cell's bound source to its engine process as UTF-8, unambiguously, regardless of host locale — either by writing UTF-8-encoded bytes over the process's input pipe, or by writing the source to a UTF-8-encoded temporary file and passing its path as an argument. A runner **MUST NOT** rely on a platform-preferred encoding (e.g. `cp1252` on Windows) for this transmission, and **MUST NOT** ship a fix that only covers one language engine.

This UTF-8 contract extends one process boundary further: a CLI that echoes a cell's captured stdout/stderr back to its own console (e.g. `pmd run --verbose`, or a failing cell's stderr dump) **MUST** ensure its own output streams write UTF-8 regardless of host locale, so that a cell's correctly-decoded output cannot crash the outer CLI process on re-encode. A runner **SHOULD** apply this at CLI startup, before any output is produced, rather than special-casing individual output call sites.

### 5.5 Caching and staleness *(SHOULD, not MUST)*

A runner **SHOULD** support skipping re-execution of a cell whose result is already known to be valid for the current run. A cache entry for a cell **SHOULD** be keyed by at least: a hash of the cell's own source text, a hash of the resolved run-context values it depends on transitively, and an identifier for the engine/command used to run it. Implementations are free to use a coarser or finer key; this spec does not mandate a storage mechanism. If a cell declares `uses` (§4.4), the cache key **MUST** be computed over the resolved, `uses`-expanded source, not just the cell's own literal text, so that editing a `lib` cell invalidates every cell that composes it.

### 5.6 No hidden state (MUST)

Given a document and no pre-existing cache, `pmd run --fresh` **MUST** be fully reproducible: identical inputs (document, environment, external data sources) **MUST** produce identical outputs, modulo the inherent non-determinism of the code being run. A runner **MUST NOT** allow a cell to observe state left behind by a cell it does not depend on.

---

## 6. Cross-language run context (`ctx`)

### 6.1 Purpose

Cells in different languages cannot share objects in memory. `ctx` is the one narrow channel a runner **MUST** provide so that, for example, a bash cell can compute a path and a Python cell downstream can read it, or a Python cell can compute a number and a PowerShell cell can print it.

### 6.2 Data model

- Keys **MUST** be strings.
- Values **MUST** be JSON-serializable (`null`, boolean, number, string, array, object) — nothing else. This is a deliberate constraint: it is what makes the value portable across arbitrary languages.
- If a cell needs to pass something that isn't naturally JSON-serializable (a dataframe, a large binary blob, a trained model), the documented pattern is: **write it to a file, and pass the file's path through `ctx`.** This spec does not attempt to solve cross-language object marshalling beyond that.

### 6.3 Required operations

Every language binding a runner ships **MUST** expose, in whatever form is idiomatic for that language, at minimum:

- `ctx_get(key)` → the stored value. If the key was never set within the current run, this **MUST** cause the calling cell to fail (non-zero exit / raised error) rather than silently returning a placeholder.
- `ctx_set(key, value)` → persists `value` under `key` before the cell's process exits.

A binding **MAY** additionally offer a `ctx_has(key)` check and a `ctx_get(key, default)` convenience form. The exact identifier names are implementation- and language-idiom-defined (e.g. `ctx.get()`/`ctx.set()` in Python, `Get-CtxValue`/`Set-CtxValue` in PowerShell, `ctx_get`/`ctx_set` shell functions in bash) — this spec fixes the semantics, not the spelling. Implementations **SHOULD** document the exact binding names they expose per engine.

### 6.4 Scoping

`ctx` **MUST** be scoped to a single run. A runner **MUST NOT** leak `ctx` values from one invocation of `pmd run`/`test`/`render` into another unless the implementation explicitly documents and opts into persistence across runs (an acceptable extension, but off by default).

---

## 7. Output and rich-display protocol

### 7.1 Standard streams

The runner **MUST** capture every cell's stdout and stderr in full.

### 7.2 File-based rich output

Before starting a cell's process, the runner **MUST** create a per-cell output directory and expose its path to the cell via an environment variable `PMD_CELL_OUT`. After the cell's process exits, the runner **MUST** scan that directory and attach every file found as a rich output of that cell. This means a bash cell can produce a rich output with a single line — `cp plot.png "$PMD_CELL_OUT/chart.png"` — with no client library required.

### 7.3 Recognized output kinds

| Extension pattern | Treated as |
|---|---|
| `.png`, `.jpg`, `.jpeg`, `.svg` | Image |
| `.csv` | Tabular data |
| `.md` | Markdown, rendered as prose in the final output |
| anything else | Generic attachment (linked, not inlined, if the render target can't embed it) |

A runner **MAY** recognize additional patterns; the table above is the minimum every conforming runner **MUST** honor.

### 7.4 Exit codes

A cell is considered successful if its process exit code equals its `expect-exit-code` attribute (default `0`). Any other exit code **MUST** be treated as a cell failure (§9.2).

---

## 8. Testing model

### 8.1 Test cells

A cell with `role=test` **MUST** declare `test-of=<id>`, referencing exactly one other cell in the same document. `pmd check` **MUST** fail if `test-of` is missing, empty, or refers to a nonexistent id.

### 8.2 Scope

A test cell's dependency closure is `{ the test-of cell } ∪ (its transitive dependencies)`, plus anything the test cell explicitly adds via its own `depends-on` (e.g. a `role=setup` fixture cell). A runner **SHOULD** restrict the `ctx` keys visible to a test cell to only those produced within this closure, to keep tests meaningful and self-contained; this is a recommendation, not a hard requirement, since enforcing it requires a namespacing mechanism this spec does not mandate.

### 8.3 `pmd test` contract

`pmd test [file] [--cell ID] [--tag TAG]` **MUST**:

1. Resolve the set of `role=test` cells to run (all of them, or the filtered subset).
2. For each, execute its dependency closure (fresh or cached, per §5.5) followed by the test cell itself.
3. Report a PASS/FAIL result per test cell id.
4. Exit non-zero if any test cell failed.

This gives a polyglot document a single, uniform `pass/fail` surface regardless of whether the underlying assertion was written with `pytest`, `Pester`, `bats`, or a bare `assert`/`exit 1`.

---

## 9. Debugging model

### 9.1 Single-cell execution

`pmd run [file] --cell ID [--fresh]` **MUST**:

1. Resolve `ID`'s transitive dependency closure.
2. For each upstream dependency, reuse a valid cache entry if one exists and `--fresh` was not passed; otherwise execute it.
3. Execute `ID` itself. `ID` **MUST** always execute (never served purely from cache) unless the runner offers an explicit `--use-cache` override — the point of this command is to re-run the thing you're debugging.

### 9.2 Failure propagation

If a cell fails (§7.4), the runner **MUST NOT** execute any cell that depends on it, directly or transitively, for the remainder of that invocation. The runner **MUST** surface the failing cell's id, the exact command/engine used, and its stderr, unmodified.

### 9.3 Patch execution against cached context

`pmd run [file] --cell ID --patch {-|FILE}` **MUST**:

1. Require `--cell ID` — there is no whole-document patch mode.
2. Resolve `ID`'s upstream dependency closure exactly as `pmd run --cell ID` does per §9.1 (reuse valid cache entries unless `--fresh`, otherwise execute), then execute the **patch source** — read from stdin (`-`) or the given file path, UTF-8 — instead of `ID`'s own source, in `ID`'s engine, with `ID`'s attributes (`env`, `timeout`, working directory) and `ID`'s resolved upstream `ctx` as input.
3. **MUST NOT** compute or store a cache key for the patch execution, and **MUST NOT** write anything back to the document. Running the same patch twice always re-executes.
4. `ctx.set(...)` calls during a patch run **MUST** be visible to that run's own subsequent reads, but **MUST NOT** persist to any cache entry or leak into a later, non-patch invocation of the same document.
5. Report output the same way `--cell` output is reported today (stdout/stderr, plus rich outputs via `PMD_CELL_OUT`).

### 9.5 Cycle detection

If the dependency graph contains a cycle, `pmd check` and `pmd run` **MUST** fail before executing anything, and **MUST** report the cycle as a sequence of cell ids.

---

## 10. CLI contract

This section defines required *behavior*, not required *internal design*. An implementation may be a single binary, a script, or a library with a thin CLI wrapper.

### 10.1 `pmd check [file] [--lint-inputs]`
Validates: unique cell ids, all `depends-on`/`test-of`/`uses` references resolve, no cycles, every fence language has a known engine, no unknown attributes. Exits `0` if valid, `2` otherwise, printing every violation found (not just the first).

`--lint-inputs` is an opt-in, off-by-default, best-effort static lint (not a hard guarantee — see §5.5): it scans each `code`/`setup`/`test` cell's source for path-shaped *tokens* — not whole string literals — that look like relative filesystem paths (a conservative heuristic based on path separators or a recognized data-file extension, applied per whitespace-delimited token after unescaping common escape sequences, configurable via frontmatter `lint.input_extensions` / `lint.ignore_patterns`) and reports, as warnings only, any such token not covered by a declared frontmatter `inputs:` entry (exact match or declared-directory prefix), plus any declared `inputs:` entry no cell source appears to reference. A `display.*` call's `name=` keyword argument (a destination filename, not an input) is excluded from the scan. `--lint-inputs` findings **MUST NOT** affect `pmd check`'s exit code.

### 10.2 `pmd run [file] [--cell ID] [--fresh] [--tag TAG] [--patch {-|FILE}]`
Executes the full graph, or a single cell's closure per §9.1. `--patch` (requires `--cell ID`) executes replacement source against `ID`'s resolved upstream context instead of `ID`'s own source, per §9.3.

### 10.3 `pmd test [file] [--cell ID] [--tag TAG]`
Per §8.3.

### 10.4 `pmd render [file] --to {html|pdf|ipynb} [--out PATH] [--with-tests]`
Per §11. `--with-tests` additionally resolves and executes every `role=test` cell's closure in the same run as the `code`/`setup` execution, and reflects each test's actual pass/fail status in the rendered output (§11.2). Without `--with-tests`, `role=test` cells render unexecuted, exactly as before.

### 10.5 Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | One or more cells or tests failed at runtime. |
| `2` | Static validation failed (`pmd check`): cycle, unresolved reference, duplicate id, unknown engine, unknown attribute. |
| `3` | CLI usage error. |

---

## 11. Rendering and self-contained output

### 11.1 Definition

A render artifact is **self-contained** if it can be opened and fully viewed — narrative, source code, captured stdout/stderr, and rich outputs from §7 — with no additional files and, for HTML, no network request required for any of that core content.

### 11.2 Required target: HTML

`pmd render file.pmd --to html` **MUST** produce a single HTML file that:

- Renders narrative Markdown as HTML.
- Shows each cell's source and declared language.
- Embeds every image output as a data URI.
- Shows captured stdout/stderr (collapsed by default is acceptable; omitted entirely is not).
- **MUST NOT** require network access to display the above. Syntax-highlighting CSS/JS **SHOULD** be embedded inline rather than loaded from a CDN; a purely cosmetic remote resource (e.g. a webfont) **MAY** be used only with a graceful fallback when offline.

With `--with-tests` (§10.4), every `role=test` cell **MUST** display its actual `passed`/`failed` status using the same status vocabulary as `code`/`setup` cells, rather than an unexecuted "not-run" status. If any test cell fails, the runner **MUST** still produce the complete HTML file — a failing render is more useful than no render — but **MUST** exit non-zero (§10.5), and **SHOULD** visually distinguish the document from one with no failing tests (e.g. a banner, not just the per-cell status color).

### 11.3 Optional targets

- **PDF** — same content contract as HTML, paginated.
- **`.ipynb`** — because a classic Jupyter notebook assumes one kernel per notebook, a polyglot `.pmd` document exported to `.ipynb` **MUST** either (a) pick one dominant language as the notebook kernel and represent other-language cells as shell/magic cells, or (b) refuse the export with a clear error naming the offending cells. Silently dropping a language's cells is not conformant.

### 11.4 Visual composition *(non-normative)*

Implementations wanting panels, tabs, or side-by-side layout in the rendered output are encouraged to reuse Pandoc/Quarto-style fenced-div syntax (`::: {.panel}` … `:::`) in the narrative, since it degrades to plain readable text when unrendered. This spec does not standardize a specific layout directive set.

---

## 12. Security considerations

A `.pmd` file executes arbitrary code, in multiple languages, on whatever host runs it. This is no different in kind from a shell script or a Jupyter notebook, but the polyglot nature means a document can reach further (filesystem, network, subprocesses in several languages at once) than a single-language script typically implies at a glance. This spec does **not** mandate a sandboxing mechanism. A conforming implementation **MUST** document its trust model (e.g. "cells run with the same privileges as the user invoking `pmd`") and **SHOULD** warn before executing a `.pmd` file that has not been executed before on this machine, in the same spirit as `chmod +x` or Jupyter's "trusted notebook" concept. Running an untrusted `.pmd` file without review is exactly as dangerous as running an untrusted script, and should be treated that way.

---

## 13. Conformance checklist

An implementation can be spot-checked against this list:

- [ ] A `.pmd` file with no cells at all renders as plain Markdown.
- [ ] Two cells with no `depends-on` execute in document order.
- [ ] A cell marked `independent: true` with no `depends-on` has no forced predecessor.
- [ ] Duplicate cell ids are rejected by `pmd check`.
- [ ] An unresolved `depends-on` reference is rejected by `pmd check`.
- [ ] A dependency cycle is detected and reported with the offending cell sequence.
- [ ] `pmd run --cell ID` executes only `ID`'s closure, not the whole document.
- [ ] A failing cell halts every downstream dependent and reports native stderr.
- [ ] `ctx_set` in one language is readable via `ctx_get` in a different language within the same run.
- [ ] `ctx_get` on a key never set fails the calling cell rather than returning a placeholder.
- [ ] A file written to `$PMD_CELL_OUT` is attached as a rich output of that cell.
- [ ] `pmd test` reports pass/fail per test cell and exits non-zero on any failure.
- [ ] `pmd render --to html` produces one file that displays correctly with no network connection.
- [ ] Re-running `pmd render` on an unchanged document with a cold cache reproduces the same visible output.
- [ ] A code cell containing a non-ASCII character (e.g. an em dash) in a comment or string literal executes identically on Windows and POSIX.
- [ ] A code cell printing a character outside the host's default locale codepage (e.g. CJK or emoji on a Windows cp1252 host) is echoed correctly by `pmd run --verbose` instead of crashing the CLI process.
- [ ] A `code` cell with `uses=X` sees `X`'s source composed ahead of its own, and editing `X` invalidates that cell's cache entry.
- [ ] A `role=lib` cell is excluded from `run`/`test`/`render` roots and cannot be a `--cell` target.
- [ ] `pmd render --with-tests` executes every `role=test` cell and reflects its actual pass/fail status in the rendered output.
- [ ] `pmd render --with-tests` on a document with a failing test still produces a complete HTML file and exits non-zero.
- [ ] `pmd check --lint-inputs` warns on a cell literal path not covered by declared `inputs:`, without affecting `pmd check`'s exit code.
- [ ] `pmd run --cell ID --patch FILE` executes the patch source against `ID`'s resolved upstream context, is never cached, and does not affect a later non-patch run of the same cell.
- [ ] `pmd run --patch` without `--cell` is rejected as a CLI usage error.

---

## 14. Worked example

````markdown
---
pmd: "0.1"
title: "Daily ingest check"
engines:
  bash: { command: "bash" }
  python: { command: "python3" }
  pwsh: { command: "pwsh -NoLogo -NoProfile -Command -" }
---

# Daily ingest check

This document fetches the day's export, summarizes it, and reports the total.

```bash {#fetch}
curl -s https://example.com/export.json -o export.json
```

```python {#compute depends-on=fetch}
import json, os
data = json.load(open("export.json"))
total = sum(row["amount"] for row in data)
ctx.set("total", total)

with open(os.environ["PMD_CELL_OUT"] + "/summary.md", "w") as f:
    f.write(f"Computed total: **{total}**")
```

```powershell {#report depends-on=compute}
$total = ctx.get("total")
Write-Host "Total for today: $total"
```

```python {#test-compute role=test test-of=compute}
assert ctx.get("total") >= 0, "total should never be negative"
```
````

Running `pmd run daily.pmd` executes `fetch → compute → report` in that order. Running `pmd run daily.pmd --cell compute` replays only `fetch` (from cache if available) and `compute`. Running `pmd test daily.pmd` executes `fetch → compute → test-compute` and reports one PASS/FAIL line. Running `pmd render daily.pmd --to html` produces one HTML file containing the narrative, all three source cells, the `summary.md` rich output rendered as prose, and the captured PowerShell stdout.

---

## 15. Appendix: relationship to prior art *(non-normative)*

| Project | What PMD borrows from it |
|---|---|
| **Jupytext** | Plain-text source paired with explicit, editor-compatible cell markers instead of JSON. |
| **marimo** | No-hidden-state execution, dependency-driven run order, "delete a cell, its state disappears." |
| **Quarto / R Markdown / knitr** | Polyglot fenced chunks in one document, rendering to one self-contained artifact. |

## 16. Open extension points *(non-normative)*

Left to implementers, deliberately not standardized here:

- Reactive re-execution (auto re-run downstream cells on edit, à la marimo/Observable).
- Fine-grained cache-key declarations (e.g. an explicit `reads=key1,key2` attribute) instead of the coarse "assume everything upstream" default in §5.5.
- Per-engine package/environment manifests.
- Editor/LSP integration (inline "run cell" affordances, hover previews of cached outputs).
- A namespacing/ACL mechanism to make the `ctx` isolation in §8.2 a hard guarantee rather than a SHOULD.
- Inline output storage (writing captured outputs back into the `.pmd` source itself, next to the cell, as an alternative to always rendering separately) — deliberately left out of the core model to keep the source diff-clean; an implementation wanting this should treat it as a distinct opt-in mode, not the default.

## 17. Versioning

**v0.1 (this document)** — initial draft. No prior versions.
