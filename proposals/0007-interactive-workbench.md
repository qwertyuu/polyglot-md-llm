# Proposal 0007: Interactive PMD Workbench

**Status:** Proposed

## Problem

PMD has a strong source and execution model, but its current local workbench is
only a viewer with editing controls added to it. It reconstructs source from
browser DOM and regular expressions. That is unsuitable for safe structural
editing, graph authoring, tests, source fidelity, or usable diagnostics.

The workbench must be replaced, not extended.

## Product Definition

The workbench is a local-first visual client for PMD documents and a shared
workspace for a human author and an agent. It is not a text editor with Run
buttons. It makes PMD blocks, cell identities, roles, dependencies, tests,
execution receipts, attachments, and agent-authored changes first-class UI
objects while keeping `.pmd` source authoritative. PMD exists in part to keep
the useful human notebook experience without the opaque document structure and
editing friction that make `.ipynb` files poor agent interfaces.

### Goals

1. Create, edit, move, duplicate, delete, run, test, inspect, and validate a
   PMD document without hand-editing fence syntax.
2. Show the difference between authored attributes and resolved execution
   behavior, especially implicit dependencies.
3. Make structural edits safe: no save against a changed revision and no
   silent change to graph semantics.
4. Remain offline-capable with packaged assets and loopback-only by default.
5. Let a human and an agent inspect, edit, execute, and verify the same document
   safely, with shared cell identities, revision preconditions, and visible
   handoff between their work.
6. Support fast exploration, rich data inspection, widgets, and debugging as
   explicit workbench modes without presenting interactive state as a durable
   or reproducible notebook result.
7. Make the active interpreter, declared inputs, cache decisions, session
   state, and prior execution receipts visible enough that users do not need a
   hidden kernel namespace to understand a run.

### Non-goals

- Making persistent sessions the default, allowing undeclared session state to
  enter the durable graph, or treating an interactive receipt as equivalent to
  an isolated execution receipt.
- Real-time multi-user or cursor-level collaborative editing. Human-agent
  collaboration is revisioned and asynchronous rather than last-writer-wins.
- A second editor-only notebook format or sidecar state file.

## Execution Tiers And Reproducibility

The workbench exposes three execution tiers. The tier is always visible beside
the Run control and in every result and receipt.

1. **Durable execution** is the existing PMD model. Every cell runs in a fresh
   process, the explicit dependency graph and declared inputs determine cache
   keys, and its receipt may be used for verification.
2. **Scratch execution** runs edited or temporary source against the resolved
   inputs of a selected cell. It is never cached and never mutates the document
   or durable graph. This is the visual counterpart of `pmd run --patch`.
3. **Session execution** is explicit and opt-in for one selected language. It
   uses an ordered, persistent language process and is marked **non-isolated**
   in the command bar, cell results, exports, and receipts. It is an
   exploration aid, not a conformant durable run.

A session has a generated ID, language, interpreter identity, environment
digest, start time, monotonically increasing execution sequence, and a state
manifest. Each session receipt records the source and declared-input hashes,
the preceding session-state hash, execution sequence, names added/changed/
removed where the language adapter can inspect them, serializable value
previews, attachment hashes, and the resulting session-state hash. Opaque
values record type, size where available, and an explicit `not_serializable`
marker rather than pretending the state can be reconstructed.

Session state never satisfies a durable graph edge and session results never
populate the normal cache. A cell that consumes undeclared session state is
visibly tainted. Promotion writes source and declared parameter inputs into the
PMD document, then offers an isolated replay of the affected downstream closure.
Only that isolated replay can clear the taint and produce a verification-eligible
receipt. Closing or resetting a session invalidates its in-memory state without
altering the document.

## Architecture

The browser maintains a parsed document model. The DOM is a projection of that
model and is never used to reconstruct source.

```text
Document { frontmatter, blocks, resolved_graph, diagnostics, revision }
NarrativeBlock { ui_id, markdown }
CellBlock { id, language, source, attributes, position }
```

The local service exposes revisioned semantic operations:

```text
GET  /api/workbench/document?path=...
POST /api/workbench/edit
     { path, base_revision, operations[] }
POST /api/workbench/execute
     { path, base_revision, roots, tier, mode, fresh, parameters }
POST /api/workbench/scratch
     { path, base_revision, target, source, tier, parameters }
POST /api/workbench/session/start
     { path, base_revision, language, interpreter }
POST /api/workbench/session/execute
     { session_id, base_sequence, target, source, parameters }
POST /api/workbench/session/reset
     { session_id, base_sequence }
GET  /api/workbench/receipts?path=...&cell=...
POST /api/workbench/share
     { path, revision, receipt_ids, artifact_ids }
```

`edit` is atomic. It returns new source, parsed model, graph impact,
diagnostics, and revision. Operations include `insert_block`, `move_block`,
`delete_block`, `replace_narrative`, `replace_cell_source`,
`update_cell_attributes`, and `rename_cell`. Conflicts are rejected, never
last-writer-wins. This service follows the revision/precondition principles of
the agent protocol.

The browser and PMD agent protocol are two clients of the same semantic
document service. Agent edits made through `pmd agent apply` become visible as
a new document revision, and workbench edits use equivalent operations and
preconditions. Neither client receives a privileged path that can silently
overwrite the other's work.

Untouched source is preserved where practical. A no-op save must not rewrite a
document. Formatting normalization is reported in the edit result.

## Workspace

The desktop UI has three linked regions:

1. **Navigator**: document selection, unsaved state, search, cell outline,
   role/test filters, compact dependency graph, and latest execution status.
2. **Notebook canvas**: ordered Markdown and code blocks, each with source,
   diagnostics, outputs, and contextual actions.
3. **Inspector**: focused-block metadata, graph relationships, tests, inputs,
   and validation. It becomes a drawer on smaller screens.

The workspace also exposes a compact collaboration activity surface rather
than a chat transcript taking over the notebook. It shows the current revision,
the actor and intent for proposed or applied semantic transactions, affected
cells and tests, source and graph diffs, verification receipts, and conflicts
that require human resolution.

## Exploration Workflows

### Scratch pane and promotion

The Inspector includes a Scratch pane bound to a target cell and its resolved
upstream closure. Edits can run immediately by keyboard command or with a
configurable debounce, but each attempt is a fresh patch process unless the
user explicitly selected Session execution. Scratch source, output, and
attachments live in receipt history, not in the PMD document or cache.

Promotion is a semantic edit with a revision precondition. It can replace the
target source, insert a new durable cell, or create a declared parameter input.
The preview shows graph impact and the isolated downstream closure that must be
rerun. Promotion never copies an interactive output into the durable cache.

### Data and variable explorers

Python tabular values can be published with a convenience display adapter for
pandas, Polars, Arrow, and objects implementing the DataFrame interchange
protocol. The Data explorer shows column names and types, shape, null counts,
bounded sampled rows, and client-side sorting and filtering of that sample.
Server-side sorting, filtering, or resampling is a new declared scratch/session
execution and receives its own receipt; it does not silently query a live
object. Rendered HTML contains the bounded snapshot and its source hash, not a
reference to process memory.

The Variable explorer makes PMD's explicit channel convenient rather than
inventing a second namespace. It shows visible `ctx` keys, producing cell,
JSON type and value, encoded size, input hash, and produced attachments with
MIME type, byte size, and content hash. Session mode may additionally show
language variables, but puts them in a separate **Session only** group and
marks opaque or undeclared values as non-reproducible.

### Rich display

`display.figure(fig)` remains supported and gains adapters for Plotly and
Altair with explicit offline HTML/JSON artifact generation. A gallery display
groups multiple image attachments with captions and stable content hashes.
Images have thumbnail, fit-to-width, and expandable original-resolution views;
the original artifact remains immutable and downloadable. Renderers sanitize
interactive HTML and package required assets locally or reject the output with
a clear diagnostic. No display adapter may depend on a live kernel after the
receipt is written.

### Widgets and reactive reruns

Widgets are parameter declarations, not mutable kernel globals. Sliders,
dropdowns, toggles, text fields, and numeric controls have a stable parameter
name, JSON-compatible type, constraints, and default. Every interaction creates
or selects a concrete parameter value that is included in the cell's declared
input manifest and cache key.

The UI may debounce and cancel superseded reactive runs. It shows the parameter
value and run receipt that produced every visible result. A useful value can be
promoted to frontmatter/project inputs or shared as part of a run bundle.
Session-backed widgets remain non-isolated until an isolated replay succeeds.

### Debugger

Tracebacks link frames to PMD cell IDs and source line/column locations. The
workbench supports cell-level breakpoints, pause/continue/step where an engine
adapter provides them, and scoped variable inspection. Debug execution always
has its own `debug` receipt class and is never cached.

The primary recovery action is **Rerun cell and downstream**, which previews
the dependency closure, invalidated cache entries, tests, and parameter values
before execution. Breakpoints and watch expressions are local workbench state;
they are never notebook inputs and cannot change normal execution behavior.

### Notebook execution controls

Every executable cell has Run, Run fresh, and Run downstream actions. The
command bar has Run all and Test. Cell status includes queued/running/passed/
failed/blocked, elapsed time, cached/fresh, execution tier, receipt ID, and a
badge explaining dependency- or input-driven invalidation. These controls call
the same graph planner as the CLI and never infer execution order from the DOM.

## Human-Agent Collaboration

The workbench treats agent work as reviewable semantic activity, not simulated
keystrokes. An agent can inspect a bounded document neighborhood, propose an
atomic transaction, apply it against a known revision, and return a recommended
verification plan. The human can review the affected cells and graph impact in
the workbench, accept or reject a proposal, continue editing from the resulting
revision, and run or authorize verification.

Agent proposals identify their base revision and may include intent, affected
cell IDs, operations, graph impact, and a source diff. Stale proposals cannot
be applied. If the human has unsaved edits, the workbench must not load or apply
an agent revision over them; it offers save, discard, or compare.

The activity surface distinguishes proposed, applied, rejected, conflicted,
and verified states. Applied changes link to the exact cells they affected.
Verification receipts show the producing document revision so a successful run
cannot be mistaken for verification of later edits. Agent-generated narrative,
source, outputs, and instructions remain untrusted document content.

The collaboration model does not require a hosted agent or network service.
Local agents use the existing PMD agent protocol and change-token workflow. A
future conversational shell may orchestrate these operations, but chat is not
the source of truth and is not required for the workbench to support agent
collaboration.

Comments attach to a document revision plus a stable block or cell ID and,
optionally, a source span. Cell permalinks encode the document-relative path,
cell ID, and revision so a later edit cannot make an old review link appear
current. Rendered review pages show comments, source and graph diffs, receipt
status, and artifact previews without enabling code execution.

**Share this run** creates a portable, content-addressed bundle containing the
PMD source at the producing revision, declared input manifest (with hashes and
redacted/omitted values recorded), engine commands and interpreter identities,
environment diagnostics, receipt(s), and selected artifacts. The manifest
states whether the run was durable, scratch, session, or debug and whether it
is reproducible from the bundle. Secrets and undeclared project files are never
included automatically.

## Environment And Migration

The command bar always shows the active interpreter for the focused language,
including resolved executable path, version, source of configuration, and
environment fingerprint. Discovery checks explicit `pmd.yaml` configuration
first, then common project environments such as `.venv`, `venv`, Conda, and
the invoking interpreter. Ambiguous environments require a choice and are not
silently persisted.

Dependency diagnostics compare imports and configured engine commands against
the active environment, report missing packages/executables, and provide the
exact diagnostic command. The UI does not install packages without an explicit
user action. Environment identity is written into every execution receipt, and
a changed interpreter marks prior results stale even when source is unchanged.

IPYNB import maps Markdown and code cells in file order, preserves stable source
text and narrative, imports displayable outputs as explicitly historical
artifacts, and records kernel/language and original execution counts as
migration metadata. It must warn about magics, shell escapes, widgets, duplicate
or missing IDs, and evidence of out-of-order hidden state. Imported output is
never entered into PMD's durable cache; an isolated PMD run is required.

PMD-to-IPYNB export preserves narrative, source, PMD cell IDs, roles,
dependencies, and the selected receipt's display order where feasible. A
single-language document receives the matching kernel metadata. Polyglot
documents use explicit magic/shell wrappers only when a configured exporter can
represent every cell; otherwise export fails and names the incompatible cells.

## Receipt History

The workbench retains prior receipts and immutable artifacts using the normal
PMD run store. History is grouped by document revision and cell, with source,
declared-input, environment, and artifact hashes visible alongside timestamps,
execution tier, duration, cached/fresh status, and parameters. Users can compare
stdout, stderr, `ctx`, tables, plots, and attachment manifests between two runs.

History never restores an old result as if it belonged to current source. A
result is labeled current only when its source, resolved upstream inputs,
parameters, interpreter/environment, and relevant artifact hashes match. GC and
retention are explicit workspace policy, with pinned receipts and shared-run
bundles protected from automatic deletion.

## Visual System And Hierarchy

The visual language is notebook-first, quiet, and information-dense without
being crowded. It must support sustained authoring, not market the product.

- The page opens directly on the document workspace. There is no oversized
  marketing hero before the first useful action.
- A single compact sticky command bar holds document selection, save state, the
  primary execution action, and an overflow menu for secondary commands.
- Cells are mostly borderless surfaces separated by rhythm and subtle
  background changes, not repeated framed cards and heavy rules. Selection,
  hover, focus, execution, and error states provide the necessary boundaries.
- Cell controls are hidden until hover or keyboard focus, except for identity,
  status, and the primary Run action. This keeps source visually dominant.
- Outputs and diagnostics are integrated regions directly after their cell;
  there is no distant results section that fragments reading and debugging.
- Empty narrative blocks collapse to a small insertion affordance until focused.
- Typography uses one coherent UI family with a purpose-built monospace face
  only for code and technical metadata. Editorial display type is unnecessary.
- The palette is neutral and low contrast by default. One restrained execution
  accent communicates run state; error, warning, and success colors are used
  semantically rather than decoratively.
- Mobile command bars do not wrap arbitrary text buttons. Primary actions stay
  compact; secondary actions move to an intentional overflow menu or drawer.

### Markdown blocks

Markdown has explicit Preview and Edit modes. Edit mode uses a Markdown source
editor, not `contenteditable` HTML. It supports add before/after, duplicate,
delete, drag or keyboard move, and source-preserving save.

### Code cells

Every cell shows language, stable ID, role, tags, resolved upstreams,
downstream consumers, linked tests, and execution state. It has Run, Run
fresh, Run downstream, and, for test cells, Run test.

Code uses a locally packaged editor component such as CodeMirror 6. Required
features are syntax highlighting, line numbers, indentation, search, undo,
redo, accessible focus, and keyboard shortcuts. Transparent textarea overlays
are explicitly rejected.

Cell headers keep only identity, status, and the primary Run action visible.
Secondary actions belong in a compact overflow menu and keyboard command
palette. This prevents repeated control clutter and keeps mobile headers a
single predictable height.

## Structural Editing

The Add menu creates Markdown, code, setup, test, scratch, and library blocks.
New cells receive valid generated IDs. Tests require a valid target before save.

Moving a cell previews changed implicit edges. The author must accept the new
resolved behavior or convert affected edges to explicit `depends-on`; moving
must never silently change execution semantics.

Delete lists consumers, tests, and library users. It is blocked until the user
chooses a valid repair transaction. Duplicate assigns a new ID and does not
rewire references without an explicit choice.

Every destructive structural operation supports Undo before the next document
revision is committed. The client must show a confirmation with impact for a
delete that removes source or invalidates consumers.

## Inspector

The Inspector edits the complete supported PMD attribute set:

- Identity: ID, language, role, tags.
- Graph: `depends-on`, independent root, and downstream consumers.
- Composition: `uses` and composed-source preview.
- Execution: timeout, environment, expected exit code, skip.
- Testing: `test-of`, linked tests, and last result.

Graph edges can be selected from the Navigator or graph as well as entered as
text. The UI distinguishes explicit dependencies from the document-order
implicit edge.

ID rename is one semantic transaction. It validates the new ID, updates
`depends-on`, `test-of`, and `uses`, displays all affected cells, and cannot
commit duplicate or dangling references.

## Diagnostics And Execution

Diagnostics have exactly three primary placements:

1. Source diagnostics appear as editor line markers and messages.
2. Cell or edge diagnostics appear below the responsible cell or on the graph
   edge for missing references, cycles, or invalid relationships.
3. Document diagnostics appear in a persistent top banner for frontmatter,
   engine, revision, or workspace problems.

The bottom report is history only, never the primary location of an error.
Runtime stderr and tracebacks appear in the failing cell panel. Blocked cells
link to the upstream failure.

Results include status, cached/fresh state, elapsed time, attachments, receipt
ID, and producing revision. Results become stale after relevant edits.

Tests are grouped by target in the Navigator and remain visible in document
order. The UI supports running all tests, one selected test and its closure,
and impacted downstream closures with a preview before execution.

### Scoped execution

Run Cell validates and resolves the selected cell's upstream closure only. An
invalid, unrelated cell is surfaced in the Navigator as a document diagnostic
but does not prevent incremental execution. A graph error inside the selected
closure blocks the action and identifies the exact node or edge. Run Notebook
continues to require a valid complete executable graph.

### Failure and save behavior

Every network operation has explicit pending, success, failure, and retry
states. Failed save, load, highlight, validation, and execution requests cannot
leave the UI in a permanent SAVING or RUNNING state.

Autosave requests capture the document path and base revision at scheduling
time. A document switch flushes or discards that request before changing the
active document; it can never save source into another document. Switching with
unsaved changes prompts the user to save, discard, or cancel. The Navigator
always distinguishes saved, saving, unsaved, conflict, and failed-save states.

The client uses the project's Markdown renderer for previews, not a bespoke
line parser. Preview fidelity includes headings, emphasis, lists, links,
blockquotes, tables where supported, and fenced code blocks.

## Accessibility And Security

All actions have keyboard access and accessible names. Focus after add, move,
delete, and run is defined and tested. Errors do not rely on color alone.

On mobile, document selection and the primary Run command stay in one compact
toolbar row. Secondary commands move to an overflow menu; Navigator and
Inspector open as drawers. The application packages a favicon to avoid console
noise during local debugging.

The workbench binds to loopback by default and warns before first execution of
a document revision. It does not claim sandboxing. Remote access requires a
separate authentication design.

## Delivery Plan

1. Replace DOM reconstruction with parsed state and revisioned semantic edits;
   add the durable/scratch/session receipt schema before adding session UI.
2. Implement the canvas, real editors, Inspector, graph preflight, environment
   discovery, variable explorer, and safe structural transactions.
3. Add durable execution streaming, per-cell controls, outputs, receipt history,
   stale-state, downstream reruns, test workflows, and the isolated scratch pane.
4. Add dataframe snapshots, Plotly/Altair artifacts, galleries, declared widgets,
   traceback links, and debug adapters without requiring persistent sessions.
5. Add language-specific session adapters behind an experimental opt-in flag,
   including state manifests, taint propagation, reset, promotion, and mandatory
   isolated replay for verification.
6. Add IPYNB import/export, comments, permalinks, review pages, share bundles,
   graph navigation, accessibility, responsive layout, and browser end-to-end
   tests including human-agent handoff and conflict flows.

No phase is complete if it serializes source from browser DOM.

## Acceptance Criteria

1. A mixed Markdown/Python/PowerShell/SQL document can be created, edited,
   saved, reopened, and represented by equivalent PMD source.
2. Reordering that changes an implicit edge is shown and cannot be silently
   saved.
3. Rename and delete cannot produce dangling references and offer repairs.
4. A test can be created, linked, run independently, and show output at that
   test cell.
5. Source, graph, runtime, and document errors appear in their specified
   locations.
6. An unchanged document round-trips byte-for-byte.
7. Browser end-to-end tests cover structural edits, revision conflicts,
   diagnostic placement, and output rendering.
8. A scheduled autosave cannot write to a document selected after it was
   scheduled, and switching with unsaved changes has save/discard/cancel flow.
9. A selected cell runs when an invalid unrelated cell exists; it is blocked
   only by errors in its own required closure.
10. Browser tests cover network failures, destructive-operation undo, Markdown
    preview fidelity, and desktop plus 390 px mobile layouts.
11. An agent transaction applied against the visible revision appears in the
    workbench with its affected cells, graph impact, diff, and verification
    state; a stale transaction or one colliding with unsaved human edits cannot
    silently replace human work.
12. A human can review and continue editing an agent-authored change without
    converting the document through another format, and both clients preserve
    unchanged source byte-for-byte.
13. The default execution tier launches a fresh process per cell, while starting
    a language session requires an explicit action and every session result is
    visibly non-isolated in the UI, receipt, rendered output, and share bundle.
14. Session state has ordered, hash-linked receipts; it cannot satisfy a durable
    dependency, populate the durable cache, or become verification-eligible
    without promotion and a successful isolated downstream replay.
15. Scratch edits rerun without changing source or cache, retain comparable
    historical receipts, and promote through a revision-checked semantic edit.
16. Dataframe snapshots expose schema, null counts, bounded samples, sorting,
    and filtering without requiring a live process after receipt creation.
17. Plotly, Altair, galleries, and original-resolution image artifacts render
    offline from immutable artifacts and are covered by sanitization tests.
18. Every widget-produced result records a typed JSON parameter value in its
    declared input manifest and cache key; reactive cancellation cannot label a
    superseded result current.
19. Traceback links resolve to the correct cell source line, debug runs are not
    cached, and rerun-downstream previews the exact invalidation closure.
20. The variable explorer distinguishes durable `ctx` and attachments from
    session-only language values and shows types, sizes, values/previews, and
    producer/content hashes.
21. Project environments are discovered deterministically, the active
    interpreter is always visible, and changing it makes incompatible prior
    results stale with actionable dependency diagnostics.
22. IPYNB import preserves narrative and source order while quarantining old
    outputs as history; export either represents every code cell and selected
    receipt or fails without silently dropping content.
23. Receipt comparison identifies source, input, environment, parameter, and
    artifact hashes, and never presents a historical output as current after
    any relevant hash changes.
24. Comments and cell permalinks are revision-aware, and a share bundle has a
    complete redacted manifest of source, inputs, environment, receipts, and
    selected artifacts with its reproducibility tier stated.

## Alternatives

Continuing to enhance the current workbench is rejected: regex parsing and DOM
serialization make its core operations unreliable. Making a Jupyter-style
kernel the document runtime is also rejected because hidden persistent state
would contradict PMD's process-isolated execution model. The constrained
session tier is acceptable only because it is opt-in, receipt-linked,
non-cacheable, visibly non-isolated, unable to satisfy durable graph edges, and
requires isolated replay before verification.
