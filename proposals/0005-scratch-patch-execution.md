# Proposal 0005: Scratch/patch execution against cached context

**Status:** Implemented (0.3.0)
**Fixes:** [known-issues.md → GAP-4](../known-issues.md#gap-4-no-sanctioned-scratch-iteration-loop)
**Touches:** `spec.md` §9.1 (single-cell execution), `cli.py`, `runner.py`

## Motivation

Building `paddy_handoff.pmd`, the actual interactive-development loop was:
run ad hoc `python -c "..."` snippets in a plain shell, outside PMD, against
freshly-loaded copies of the same parquet files, to check a column name, a
correlation, or the runtime of a candidate bootstrap sample size — and only
once a snippet was verified correct, type a cleaned-up version into an actual
`.pmd` cell and run `pmd run --cell ID --verbose` to confirm.

This isn't a workflow bug so much as a workflow *gap*: PMD's actual execution
model (per-cell isolation, resolved upstream context, declared inputs, a
consistent engine invocation) has no cheaper mode than "commit a real cell to
the document and run it." `role=scratch` (spec.md §4.6) is close in spirit
but solves a different problem — it marks a cell that's *permanently*
excluded from every pipeline, not a temporary probe against an *already-
resolved* upstream state that never needs to touch the document at all.

The result is that the fast part of development happens with zero relation
to the tool: no shared context resolution, no consistent engine/venv
selection, no `PMD_CELL_OUT` conventions — all of that gets manually
re-derived by hand in the throwaway shell commands, then thrown away.

## Proposal

Add a `--patch` mode to `pmd run`:

```console
pmd run file.pmd --cell ID --patch -           # read replacement source from stdin
pmd run file.pmd --cell ID --patch snippet.py  # read replacement source from a file
```

1. `--patch` **MUST** require `--cell ID` (patching only makes sense against
   a specific target; there is no whole-document patch mode).
2. The runner **MUST** resolve `ID`'s upstream dependency closure exactly as
   `pmd run --cell ID` already does today (§9.1: reuse valid cache entries
   unless `--fresh`, otherwise execute), then execute the **patch source**
   — not `ID`'s own source — in `ID`'s engine, with `ID`'s attributes
   (`env`, `timeout`, working directory) and `ID`'s resolved upstream `ctx`
   as input.
3. **The patch run MUST NOT be cached and MUST NOT write back to the
   document.** No cache key is computed or stored for it; running the same
   patch twice always re-executes. This is the core property that makes it
   safe to use for exploration: nothing about a `--patch` run has any
   persistent effect on the document, its cache, or any downstream cell's
   resolution.
4. `ctx.set(...)` calls in a patch run **MUST** be visible to the patch
   process's own subsequent reads within that same run (so a multi-statement
   probe still works normally) but **MUST NOT** persist to any cache entry
   or leak into a later, non-patch `pmd run`/`test`/`render` invocation of
   the same document — matching the existing per-run `ctx` scoping rule
   (§6.4) with "a patch invocation" simply being one more kind of run.
5. Output **MUST** be reported the same way `--cell` output is today (stdout/
   stderr, plus rich outputs scanned from `PMD_CELL_OUT` if the patch chooses
   to write any) — no new output format, so the muscle memory of reading
   `pmd run --cell` output transfers directly.

### What this deliberately does not do

- It does not add a persistent REPL or a long-lived kernel process. Each
  `--patch` invocation is still a single fresh process, exactly like every
  other cell execution (§5.4) — this proposal changes *what source runs*,
  not the process-per-execution model itself. A REPL/kernel mode would be a
  much larger change to the isolation guarantees the format is built around,
  and isn't needed to solve the observed problem (which was "avoid re-deriving
  context by hand," not "avoid interpreter startup cost").
- It does not let a patch declare new `depends-on` edges or reach cells
  outside `ID`'s existing closure — the resolved context a patch runs against
  is exactly what `ID` itself would see, no more.

## Alternatives considered

- **Extend `role=scratch` to be runnable with `--include-scratch`, and tell
  people to use scratch cells for this.** Spec.md §4.6 already allows this
  ("Runners MAY offer an explicit `pmd run --include-scratch` for interactive
  use") and it's a reasonable complementary feature, but it solves a
  different problem: a scratch *cell* is still a permanent, committed part of
  the document (it has an id, sits in the file, shows up in `pmd check`,
  needs to be deleted by hand when no longer wanted). The friction observed
  was specifically about *not* wanting to touch the document at all for a
  probe that might be wrong, might be repeated ten times with small
  variations, and has no reason to exist once the answer is known.
  `--include-scratch` and `--patch` are not mutually exclusive; both are
  worth having.
- **A real REPL (`pmd shell file.pmd --cell ID`) that keeps a warm process
  and lets you type statements interactively.** More powerful, and arguably
  what a human would reach for first, but changes the execution model far
  more (a warm process across multiple inputs is a small kernel, which is
  exactly what §5.4 rules out for documents proper) and is a much bigger
  implementation lift for a benefit — faster iteration — that `--patch`
  already delivers for the observed use case (batch probes with a fresh
  process each time, which is fast enough in practice for the interpreter/
  library-import costs seen here). Not rejected outright, just proposed as a
  separate, later proposal if `--patch` turns out to be insufficient.

## Open questions

- Should `--patch` support targeting a *hypothetical* cell that doesn't exist
  in the document yet (i.e., also accept `--depends-on ID` instead of
  `--cell ID`, for probing "what would a new cell after X see" before ever
  writing that cell for real)? Would close the loop even further but adds a
  second CLI shape; deferred rather than folded into this proposal.
- Interaction with `pmd agent verify`'s authorization model
  (`agent-spec.md`): `--patch` executes arbitrary code exactly like any other
  `run`, so it should carry the same "cells execute with your privileges"
  warning (spec.md §12) as everything else — no special exemption, just
  flagged so it isn't overlooked as a "just a probe, so it's safe" special
  case.
