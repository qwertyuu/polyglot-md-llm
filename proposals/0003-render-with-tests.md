# Proposal 0003: `pmd render --with-tests`

**Status:** Implemented (0.3.0)
**Fixes:** [known-issues.md → GAP-2](../docs/known-issues.md#gap-2-render-silently-excludes-test-cells)
**Touches:** `spec.md` §8 (testing model), §11.2 (required HTML render
target), `cli.py`, `render.py`

## Motivation

A document written so its headline claims are machine-checked — three
`role=test` cells asserting specific quantitative properties, in the
`paddy_handoff.pmd` case study — renders to HTML with those three cells shown
as grey, empty "not-run" blocks, because `render_html()` calls
`Runner().run(document, fresh=fresh)` with the default `tests=False`
(`runner.py`, `Runner.run`), which restricts execution roots to
`{"code", "setup"}` and never includes `role=test` cells (§8.1).

This is not a spec violation — §11.2 never requires test cells to run as part
of rendering — but it produces a specific, avoidable failure mode: **the
rendered artifact cannot prove the claims it makes.** The verification
happened, separately, via `pmd test`, in a terminal the recipient of the
rendered document never sees. The document's own stated purpose — in this
case, "every number here is recomputed live, not copied from a report" — is
only actually demonstrated by a command the reader has no access to and no
reason to trust ran, let alone ran against the same revision they're looking
at.

## Proposal

1. Add a `--with-tests` flag to `pmd render`:

   ```console
   pmd render file.pmd --to html --with-tests [--fresh] [--out PATH]
   ```

   When passed, the runner **MUST** additionally resolve and execute every
   `role=test` cell's closure (in the same run, sharing the same cache
   decisions as the `code`/`setup` execution — i.e. exactly the union of
   `roots` that `pmd run` and `pmd test` would each select separately, not
   two independent runs) before rendering.

2. Each rendered test cell **MUST** display its actual `passed`/`failed`
   status using the render target's existing status vocabulary
   (`render.py`'s `_cell_html` already has a `status-passed` /
   `status-failed` CSS class pair defined and used for `code`/`setup`
   cells — this is a matter of populating `by_id` with the test cell's real
   `CellResult` instead of leaving it absent, not inventing new rendering
   logic).

3. If any test cell fails under `--with-tests`, `pmd render` **MUST** still
   produce the HTML file (a failing render is more useful than no render —
   the reader should be able to see *which* claim broke), but **MUST** exit
   non-zero, matching `pmd test`'s existing exit-code contract (spec.md
   §10.5, code `1`), and **SHOULD** visually distinguish a document with a
   failing test from one with none (e.g. a banner at the top, not just the
   per-cell status color, since a reader skimming a long document
   shouldn't have to find the one red cell among many green ones to know the
   document's overall claim status).

4. Without `--with-tests`, behavior **MUST** be unchanged from today (test
   cells render as `not-run`, exit code reflects only `code`/`setup` cell
   success) — this is additive, not a default-behavior change. A document
   with no test cells at all is unaffected either way.

## Conformance addition

Add to spec.md §13 (conformance checklist):

- [ ] `pmd render --with-tests` executes every `role=test` cell and reflects
      its actual pass/fail status in the rendered output.
- [ ] `pmd render --with-tests` on a document with a failing test still
      produces a complete HTML file and exits non-zero.

## Alternatives considered

- **Make test execution the default for `render`, no flag.** Rejected: a
  render is sometimes wanted fast, or wanted for a document mid-edit where
  tests are known to be failing/incomplete and that's not the point of this
  particular render. Keeping it opt-in matches the existing `run`/`test`
  split (spec.md never merges them) and doesn't silently make every render
  slower or more failure-prone for documents that don't need this guarantee.
- **A separate `pmd verify --to html` command instead of a render flag.**
  Rejected as unnecessary surface area — this is a render with one extra
  step folded into the same execution pass PMD already does internally
  (`render_html` already wraps a `Runner().run(...)`); a new top-level
  command for what's structurally "render, but also run the tests" adds a
  second thing to remember for one flag's worth of behavior.
- **Show test source and a static "not verified in this render" label
  instead of running them.** This is closer to current behavior and cheaper,
  but doesn't solve the actual problem (the reader still can't tell if the
  claims are true from the artifact alone) — it just makes the gap explicit
  instead of silent. Worth doing as a documentation fix regardless of whether
  `--with-tests` ships (see the `render.py` note in Open Questions), but not
  a substitute for it.

## Open questions

- Should a **default** (no-flag) render at least *label* unexecuted test
  cells more clearly than the current bare "not-run" status — e.g. "not
  verified in this render, run `pmd test` to check" — as a cheap partial fix
  even before `--with-tests` exists? Seems like a good, small, independent
  change regardless of this proposal's fate.
- Interaction with `agent-spec.md`'s `pmd agent verify`: that command already
  has its own authorization-gated execution model (`--allow-execution`) for a
  different reason (untrusted-content safety, not rendering). `--with-tests`
  should probably inherit the same "this executes code" warning posture as
  every other `run`/`test` invocation (spec.md §12) rather than introduce a
  third authorization model — flagged for whoever implements this to check
  against `agent-spec.md`'s existing execution-authorization sections.
