# Proposal 0015: Reader-oriented HTML render controls

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 3.5
**Touches:** `render.py`, `cli.py`, HTML render profile

## Motivation

The cell graph and source disclosures are useful for developers but distract
from decision notes intended for non-technical readers. The document content
should not need to fork merely to address a different audience.

## Proposal

1. HTML rendering **MUST** accept `--hide-graph` and `--hide-source`.
2. The flags **MUST** affect presentation only; execution, outputs, statuses,
   narrative, and the source document remain unchanged.
3. The default developer-oriented HTML remains backward compatible with both
   graph and source visible.

## Alternatives considered

- **A single `--reader` preset.** Convenient, but explicit orthogonal flags are
  composable and can later be grouped by a preset without losing control.
- **Frontmatter-only configuration.** Audience is a property of one render, not
  necessarily of the source document.
