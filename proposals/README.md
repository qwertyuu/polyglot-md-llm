# Proposals

Design proposals for `polyglot-pmd`, written against real friction recorded in
[`../known-issues.md`](../known-issues.md) rather than speculative wishlist
items. Each proposal is scoped to one change, follows the same RFC-2119
conformance language as [`../spec.md`](../spec.md) (§0), and is written so it
could become a dated `spec.md` addendum or `agent-spec.md` section if accepted
— not so it stays a standalone opinion piece.

**Status key** used in each proposal's header:

| Status | Meaning |
|---|---|
| `Proposed` | Written up, not reviewed, not implemented. |
| `Accepted` | Reviewed and agreed; not yet implemented. |
| `Implemented` | Shipped; see `CHANGELOG.md` for the version. |
| `Rejected` | Considered and declined; kept for record, with the reason in the proposal's "Alternatives considered" section. |

## Index

| # | Title | Status | Fixes / relates to |
|---|---|---|---|
| [0001](0001-utf8-safe-cell-source.md) | UTF-8-safe cell source transmission | Implemented (0.3.0) | [BUG-1](../known-issues.md#bug-1-non-ascii-in-a-code-cell-crashes-with-a-misleading-pep-263-error) |
| [0002](0002-shared-library-cells.md) | Shared library cells | Implemented (0.3.0) | [GAP-1](../known-issues.md#gap-1-no-cross-cell-code-sharing) |
| [0003](0003-render-with-tests.md) | `pmd render --with-tests` | Implemented (0.3.0) | [GAP-2](../known-issues.md#gap-2-render-silently-excludes-test-cells) |
| [0004](0004-declared-input-linting.md) | Declared-input linting | Implemented (0.3.0) | [GAP-3](../known-issues.md#gap-3-declared-inputs-is-unchecked) |
| [0005](0005-scratch-patch-execution.md) | Scratch/patch execution against cached context | Implemented (0.3.0) | [GAP-4](../known-issues.md#gap-4-no-sanctioned-scratch-iteration-loop) |
| [0006](0006-utf8-safe-cli-output.md) | UTF-8-safe CLI output | Implemented (0.4.0) | [BUG-2](../known-issues.md#bug-2-cli---verbose-echo-of-cell-output-still-crashes-outside-cp1252) |

## How to review one

Each file is short by design (one change, one page or less). Read the
**Motivation** section first — if the motivating scenario doesn't match a
problem you actually have, the rest doesn't matter. The **Proposal** section
is written to be implementable as stated; the **Alternatives considered**
section exists so a reviewer doesn't have to re-derive the options that were
already ruled out and why.
