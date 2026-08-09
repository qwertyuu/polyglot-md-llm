# Proposal 0004: Declared-input linting

**Status:** Implemented (0.3.0)
**Fixes:** [known-issues.md → GAP-3](../known-issues.md#gap-3-declared-inputs-is-unchecked)
**Touches:** `spec.md` §5.5 (caching and staleness), `cli.py` (`check`),
`runner.py` (`_declared_inputs`)

## Motivation

Spec.md §5.5 makes cache staleness a `SHOULD`, and this implementation
satisfies it via frontmatter `inputs:` — a list of paths whose content hashes
participate in every cell's cache key (`_input_fingerprints` /
`Cache.key` in `runner.py`). This works correctly *if* the list is complete.
Nothing checks that it is.

Concretely: a cell can call `pd.read_parquet("data/new_file.parquet")`
without that path appearing anywhere in frontmatter `inputs:`, and both
`pmd check` and `pmd run` succeed silently. The cell's cache key is then
insensitive to that file's contents — editing `data/new_file.parquet` later
does not invalidate the cell's cache entry. This is the worst kind of bug:
not a crash, not a validation error, just a quietly wrong cached answer that
looks identical to a correct one until someone happens to run `--fresh` and
notices the numbers moved.

Building `paddy_handoff.pmd` required maintaining a 9-entry `inputs:` list
across 5 distinct data files and 4 pre-existing PNGs, purely by inspection,
with the only feedback loop being "did I remember."

## Proposal

A **fully general** solution (tracing actual file-descriptor opens across
five heterogeneous language engines, each in its own subprocess) is out of
proportion to the problem and platform-fragile (would mean strace on Linux,
ETW or a Detours-style hook on Windows, dtruss on macOS, per engine). This
proposal is deliberately a **best-effort static lint**, opt-in, that catches
the common case cheaply instead of promising a guarantee it can't keep.

1. Add `pmd check --lint-inputs`, off by default (so it never becomes a
   surprise failure in an existing pipeline), which:
   - Scans each `code`/`setup`/`test` cell's source text for string literals
     that look like relative filesystem paths (a conservative heuristic:
     contains a path separator or a recognized data-file extension —
     `.parquet`, `.csv`, `.json`, `.db`, `.duckdb`, `.png`, `.jpg`, `.txt`,
     configurable via frontmatter, see below — and does not look like a URL
     or an f-string with unresolved interpolation).
   - Reports, as **warnings** (never hard errors — this is a heuristic, false
     positives are expected and must not block `pmd check`'s exit code),
     every such literal whose resolved path is not a prefix-match of any
     declared `inputs:` entry.
   - Also reports, symmetrically, any declared `inputs:` entry that no
     cell's source appears to reference at all — a likely-stale declaration,
     equally worth surfacing.

2. Frontmatter gains an optional `lint`:

   ```yaml
   lint:
     input_extensions: [".parquet", ".csv", ".json", ".duckdb", ".png"]
     ignore_patterns: ["https?://", "^/tmp/"]
   ```

   both keys optional, both purely advisory to the linter, with sane
   built-in defaults so most documents need neither.

3. This is explicitly **not** proposed as part of `pmd check`'s default,
   non-`--lint-inputs` behavior, and explicitly **not** proposed as
   something `pmd run` enforces at runtime. It is a lint, not a guarantee —
   overselling it as a correctness mechanism would be worse than not having
   it, given how easy it is to write a cell that reads a path built from
   string concatenation or a variable the static scan can't see through.

## Alternatives considered

- **Runtime file-access tracing per engine (strace/ETW/dtruss).** Rejected as
  the default mechanism: real guarantee, but per-platform, per-engine
  implementation cost that's disproportionate given the lint alternative
  catches the actual observed case (a literal path in `pd.read_parquet(...)`)
  cheaply. Worth revisiting as an opt-in `--strict-inputs` mode on POSIX only
  if the lint's false-negative rate turns out to matter in practice — not
  proposed here.
- **Require every cell to declare its own inputs via a cell attribute (e.g.
  `reads=data/x.parquet`) instead of one document-level list.** This is
  explicitly named as an open extension point already in spec.md §16
  ("fine-grained cache-key declarations... instead of the coarse 'assume
  everything upstream' default"). It would make the *declaration* more
  precise (per-cell instead of per-document) but does nothing by itself
  about the *checking* problem this proposal targets — a per-cell `reads=`
  attribute can be just as incomplete as today's document-level list. The
  two ideas are complementary, not alternatives; this proposal's lint would
  apply equally well to a future per-cell declaration scheme.
- **Infer `inputs:` automatically and drop the frontmatter list entirely.**
  Rejected — that's the runtime-tracing approach above wearing a different
  hat, with the same platform-fragility problem, plus it removes the
  human-authored, human-reviewable declaration that makes a cell's external
  dependencies legible at a glance in the frontmatter (a real property worth
  keeping even if it's not automatically verified).

## Open questions

- Should `--lint-inputs` warnings be promotable to hard errors via a flag
  (`--lint-inputs=strict`) for teams that want to fail CI on drift, given the
  false-positive risk is presumably lower once a project's real path
  patterns stabilize? Left as a natural follow-on, not required for the
  initial version.
- Directory-valued `inputs:` entries (already supported — spec.md /
  README's "Files and directories are supported; directory fingerprints
  include every contained file") make the "entry never referenced" half of
  the lint noisier (a cell reading one file from a declared directory looks,
  to a literal-string scan, like it's referencing a different, more specific
  path than the directory entry). The lint should match a literal path
  against either an exact `inputs:` entry or a declared-directory prefix;
  noted here so the implementer doesn't miss the directory case.
