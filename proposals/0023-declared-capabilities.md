# Proposal 0023: Declared external capabilities

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 4.3
**Touches:** frontmatter validation, static linting, agent inspection and plans

## Motivation

PMD cannot enforce network and system isolation on every host, but an
orchestrator still needs to know what a notebook intends to contact before it
runs. Today that intent exists only in prose or executable source.

## Proposal

1. Frontmatter **MAY** declare `capabilities.network` and `capabilities.ssh` as
   lists of host names or addresses.
2. `check` **MUST** reject malformed capability declarations and **SHOULD** warn
   when literal HTTP(S) or SSH hosts in executable source are undeclared.
3. `agent inspect` and verification plans **MUST** expose the normalized
   declarations even when frontmatter source is omitted.
4. Declarations are intent metadata, not enforcement. Receipts and plans
   **MUST NOT** describe them as sandbox guarantees.

## Alternatives considered

- **Wait for enforceable sandboxing.** Policy decisions benefit from declared
  intent now, independently of platform enforcement.
- **Infer capabilities only.** Dynamic hosts cannot be inferred reliably and a
  public declaration is a more stable interface for orchestration.
