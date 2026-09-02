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
| [0007](0007-interactive-workbench.md) | Interactive PMD workbench | Proposed | Human authoring and debugging |
| [0008](0008-render-fidelity.md) | Render fidelity for preformatted output and Markdown tables | Implemented (0.6.0) | PMD 0.5.0 field report 1.1-1.2 |
| [0009](0009-typed-csv-display.md) | Explicit `display.csv` input contract | Implemented (0.6.0) | PMD 0.5.0 field report 1.3 |
| [0010](0010-actionable-policy-blocks.md) | Actionable verification block reasons | Implemented (0.6.0) | PMD 0.5.0 field report 1.4 |
| [0011](0011-documentary-fences.md) | Documentary language fences | Implemented (0.6.0) | PMD 0.5.0 field report 1.5 |
| [0012](0012-narrative-replacement-evidence.md) | Narrative replacement evidence | Implemented (0.6.0) | PMD 0.5.0 field report 1.6 |
| [0013](0013-text-rendering.md) | Reader-visible text rendering | Implemented (0.6.0) | PMD 0.5.0 field report 3.1 |
| [0014](0014-document-tests.md) | Tests over the rendered document | Implemented (0.6.0) | PMD 0.5.0 field report 3.2 |
| [0015](0015-reader-render-profile.md) | Reader-oriented HTML render controls | Implemented (0.6.0) | PMD 0.5.0 field report 3.5 |
| [0016](0016-rendered-agent-inspection.md) | Bounded rendered cell inspection | Implemented (0.6.0) | PMD 0.5.0 field report 3.1 |
| [0017](0017-stale-measurements.md) | Staleness metadata for measurements | Implemented (0.6.0) | PMD 0.5.0 field report 3.3 |
| [0018](0018-context-overrides-and-sweeps.md) | Run-scoped context overrides and sweeps | Implemented (0.6.0) | PMD 0.5.0 field report 3.4 |
| [0019](0019-run-comparison.md) | Compare outputs with a previous run | Implemented (0.6.0) | PMD 0.5.0 field report 3.6 |
| [0020](0020-named-narrative-sections.md) | Named narrative sections | Implemented (0.6.0) | PMD 0.5.0 field report 3.7 |
| [0021](0021-typed-output-contracts.md) | Typed context output contracts | Implemented (0.6.0) | PMD 0.5.0 field report 4.1 |
| [0022](0022-callable-notebooks.md) | Callable notebooks | Implemented (0.6.0) | PMD 0.5.0 field report 4.2 |
| [0023](0023-declared-capabilities.md) | Declared external capabilities | Implemented (0.6.0) | PMD 0.5.0 field report 4.3 |
| [0024](0024-provenance-attestations.md) | Interpreter-bound provenance attestations | Implemented (0.6.0) | PMD 0.5.0 field report 4.4 |
| [0025](0025-streaming-execution-events.md) | Streaming execution events | Implemented (0.6.0) | PMD 0.5.0 field report 4.5 |
| [0026](0026-structured-failures.md) | Structured execution failures | Implemented (0.6.0) | PMD 0.5.0 field report 4.6 |
| [0027](0027-shipped-agent-skill.md) | Capability-synchronized agent skill | Implemented (0.6.0) | Agent adoption of new PMD features |
| [0028](0028-platform-native-init.md) | Platform-native `pmd init` path | Implemented (0.6.1) | POSIX initialization failure |
| [0029](0029-typed-output-cache-key-integrity.md) | Typed-output cache-key integrity | Implemented (0.6.1) | Cache and receipt evidence |
| [0030](0030-concurrent-freshness-writes.md) | Concurrent freshness writes | Implemented (0.6.1) | Windows cache concurrency |

## How to review one

Each file is short by design (one change, one page or less). Read the
**Motivation** section first — if the motivating scenario doesn't match a
problem you actually have, the rest doesn't matter. The **Proposal** section
is written to be implementable as stated; the **Alternatives considered**
section exists so a reviewer doesn't have to re-derive the options that were
already ruled out and why.
