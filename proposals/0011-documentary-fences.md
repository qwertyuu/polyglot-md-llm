# Proposal 0011: Documentary language fences

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 1.5
**Touches:** `parser.py`, cell discovery

## Motivation

Common Markdown fences such as `json`, `console`, and `diff` are examples, not
programs. Treating every named fence as a cell makes otherwise ordinary
technical prose fail `pmd check` with a missing-engine error.

## Proposal

1. Unannotated fences named `text`, `console`, `json`, `yaml`, `yml`, `diff`,
   `log`, or `toml` **MUST** remain narrative Markdown and **MUST NOT** become
   PMD cells.
2. The same languages with an explicit `{...}` PMD attribute block **MUST**
   retain cell semantics. This provides an unambiguous opt-in for a custom
   engine and keeps missing-engine validation useful.
3. Bare fences for built-in executable languages remain implicit cells.

## Alternatives considered

- **Only execute fences with attributes.** This is simpler but breaks PMD's
  established low-ceremony bare Python and shell cells.
- **Treat every unknown language as narrative.** A misspelled executable
  language would silently stop running. The conservative allowlist avoids that
  failure mode.
