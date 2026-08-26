# Proposal 0002: Shared library cells

**Status:** Implemented (0.3.0)
**Fixes:** [known-issues.md → GAP-1](../docs/known-issues.md#gap-1-no-cross-cell-code-sharing)
**Touches:** `spec.md` §4.4 (cell attributes), §4.6 (roles), §5.4 (process
isolation), `parser.py`, `bindings.py`

## Motivation

Spec.md §5.4 is unambiguous, and correctly so, that cells share no
language-level memory. That rule protects the document's most important
property: no hidden state, full reproducibility from source. But it currently
applies to *code* and *data* identically, and those have different reuse
needs:

- **Data** produced by one cell and consumed by another has a designated,
  correct channel: `ctx` (§6), for JSON-serializable values, or a file path
  passed through `ctx` for anything larger.
- **Code** — a constant table, a small helper function, an import alias —
  that several cells want to use *identically* has no channel at all. The
  only current option is to retype it, verbatim, in every cell that needs it.

In the `paddy_handoff.pmd` case study, a 12-entry `BOT_SIDE` dict and a
parallel `BOT_TIGHTNESS` dict had to be copy-pasted into three separate
cells. Nothing in the format or the runner enforces the three copies stay
identical; a future edit to one is a silent correctness bug in the other two
until someone notices by inspection.

This is squarely a maintainability problem, not a correctness-of-execution
problem — the isolation model itself is doing exactly what it's supposed to.
The gap is that there's no sanctioned way to reuse *text*, only *values*.

## Proposal

Introduce a fifth role, `lib`, alongside the existing `code` / `setup` /
`test` / `scratch` (spec.md §4.6):

```
| Role  | Meaning                                                          |
|-------|-------------------------------------------------------------------|
| `lib` | Never executed on its own. Its source text is textually prepended |
|       | to the source of any cell that names it via `uses=`, before that  |
|       | cell's own binding preamble. Purely a source-composition step —   |
|       | it does not run as a separate process and produces no ctx/output  |
|       | of its own.                                                        |
```

A new cell attribute, `uses`, comma-separated like `depends-on`, is valid on
`code`/`setup`/`test` cells and names one or more `lib` cells **in the same
language**:

````markdown
```python {#bot_constants role=lib}
BOT_SIDE = {
    "6z7257126u1c7bvw": "light",
    # ...
}
BOT_TIGHTNESS = {
    "6z7257126u1c7bvw": 0.170,
    # ...
}
```

```python {#bot_roster depends-on=setup uses=bot_constants}
# BOT_SIDE and BOT_TIGHTNESS are in scope here, textually included —
# not imported, not shared memory, just concatenated source.
for gid, side in BOT_SIDE.items():
    ...
```
````

### Semantics

1. `uses` is a **compile-time source-composition** step, resolved by the
   runner before dispatch, not a runtime dependency. A `lib` cell named in
   `uses` **MUST** be concatenated (in `uses` order, each separated by a
   newline) immediately after the language binding preamble
   (`source_with_binding` in `bindings.py`) and before the using cell's own
   source. This keeps the process-isolation guarantee in §5.4 completely
   intact: nothing crosses a process boundary that wasn't already textually
   present in the composed script handed to that one process.
2. A `lib` cell **MUST NOT** declare `depends-on`, `independent`, or
   `test-of` — it participates in no execution graph, only in source
   composition, so those attributes are meaningless for it. `pmd check`
   **MUST** reject a `lib` cell that sets any of them, the same way it
   already rejects `depends-on` on `role=scratch` (spec.md §4.4 table,
   `graph.py`'s `validate()`).
3. `pmd check` **MUST** reject a `uses` reference to a cell whose `language`
   differs from the referencing cell's, and **MUST** reject a `uses`
   reference to a non-`lib` cell (composing in a `code` cell's *side effects*,
   not just its text, is out of scope for this proposal — see "Alternatives
   considered").
4. Cache-key composition (`Cache.key` in `runner.py`) **MUST** include the
   resolved, composed source (post-`uses`-expansion), not just the using
   cell's own literal text — otherwise an edit to a `lib` cell would not
   invalidate the cache of cells that use it. This is a natural consequence
   of "compile-time composition": the composed text simply *is* the cell's
   effective source for every purpose downstream of parsing, including
   caching, `pmd render`'s "View source" panel (which **SHOULD** show the
   composed form, or at minimum flag that a `lib` was inlined, so the reader
   isn't confused about where a name came from), and the `pmd agent inspect`
   protocol's `include_source`.
5. `lib` cells are excluded from `run`/`test`/`render` roots exactly like
   `scratch` (they cannot be a `--cell` target), but — unlike `scratch` —
   they are not "throwaway": editing one is a real, cache-invalidating change
   to every cell that uses it, and `pmd agent inspect`'s dependency view
   (agent-spec.md) **SHOULD** report `uses` edges alongside `depends-on`
   edges when asked for a cell's upstream context, since an agent editing a
   `lib` cell needs to know its blast radius the same way it needs to know a
   `depends-on` blast radius today.

## Alternatives considered

- **Let `code` cells `depends-on` a "pure" upstream cell and inherit its
  `ctx`.** Already possible today and already used for data. Doesn't solve
  this problem because `ctx` values must be JSON-serializable (§6.2) — a
  function or a class can't cross that boundary, only the *data* a function
  would compute could, which brings back the "duplicate the surrounding code
  anyway" problem the moment two cells need to use a shared value
  differently.
- **A real shared-kernel/import mechanism (e.g. actually `import` from a
  `.py` file on disk).** Rejected as the default: it reintroduces exactly the
  hidden-state risk §5.4 exists to prevent (a `.py` file on disk, edited
  outside the document, silently changes cell behavior with no visible diff
  in the `.pmd` file itself). Nothing stops an author from doing this today
  by having a cell read a project's `src/` modules via `sys.path` — as
  `paddy_handoff.pmd` in fact does for one constant it *didn't* end up
  duplicating — but that's an escape hatch that trades reproducibility for
  convenience, not something the spec should bless as the primary mechanism.
  `lib` cells keep the shared code inside the document, in the diff, in the
  cache key.
- **Allow `uses` to reference a `code` cell, not just `lib`.** Rejected:
  it's unclear what "reuse this cell's *source*, but not its execution or
  its `ctx` output" means for a cell that's also, separately, an executable
  step with its own dependencies — two different reuse semantics collapsing
  onto one role invites exactly the kind of implicit magic §5.2 explicitly
  tries to avoid ("never inferred by magic the author cannot inspect").
  Keeping `lib` a distinct, execution-free role keeps the two concerns
  separate.

## Open questions

- Should `uses` support cross-language composition for engines that can
  literally source another language's file unmodified (e.g. a `sh` cell
  `uses`-ing a `bash` cell)? Scoped out of this proposal; same-language-only
  is the safe default and covers the observed case.
- Does a `lib` cell's source get its own syntax-highlighted, standalone
  "View source" block in `pmd render`, or only appear inlined inside every
  cell that uses it? Leaning toward "both" (a `lib` cell renders its own
  narrative-adjacent block, marked "not executed — composed into: X, Y, Z",
  plus inlined visibility in each user) but not settled.
