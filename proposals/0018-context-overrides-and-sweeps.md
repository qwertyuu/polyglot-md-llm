# Proposal 0018: Run-scoped context overrides and sweeps

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 3.4
**Touches:** runner inputs and `run`/`test` CLI

## Motivation

Sensitivity analysis currently requires editing the notebook or duplicating a
loop inside it. Both approaches mix scenario inputs with the durable document
and weaken cache clarity.

## Proposal

1. `pmd run` and `pmd test` **MUST** accept repeatable `--set PATH=JSON` values.
   Dot-separated paths construct nested JSON objects available to every root.
2. Overrides **MUST** be run-scoped, leave the document unchanged, and
   participate in cell cache keys.
3. `pmd run --sweep PATH=JSON,JSON,...` **MUST** execute one isolated run per
   value and label each result. A first implementation accepts one sweep axis.
4. `--set` values apply to every sweep variant and the swept path wins on
   conflict.

## Alternatives considered

- **Rewrite frontmatter temporarily.** This creates revision races and makes a
  transient scenario look like document state.
- **Implement sweeps inside cells.** That loses per-scenario cache identity and
  prevents the CLI from comparing or supervising variants independently.
