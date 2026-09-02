# Proposal 0019: Compare outputs with a previous run

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 3.6
**Touches:** cache run history, result model, `run` CLI

## Motivation

For monitoring notebooks, the important result is often not the latest output
but which outputs changed since a known run. Cell cache entries already contain
most evidence, but they do not provide a stable run-level identity or summary.

## Proposal

1. Every completed run **MUST** receive a `run_id` and persist a lightweight
   snapshot under the configured cache directory.
2. Snapshots **MUST** bind to the canonical document path and record per-cell
   status plus digests of stdout, stderr, context, and rich outputs.
3. `pmd run FILE --compare-with RUN_ID` **MUST** report added, removed, and
   changed cell fields, or state that no output changed.
4. Comparing a run from another document or an unknown id **MUST** fail clearly.

## Alternatives considered

- **Compare cache keys only.** A cache key can change while observable output
  remains identical, and it does not explain which output changed.
- **Persist full run output again.** Digests and output names are sufficient for
  comparison and avoid duplicating potentially large artifacts.
