# Proposal 0013: Reader-visible text rendering

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 3.1
**Touches:** `render.py`, `cli.py`, render target conformance

## Motivation

`run` verifies execution and `render --to html` creates the artifact, but an
agent cannot inspect what the reader sees without parsing HTML itself. This
made broken tables and layout-sensitive output invisible inside the PMD loop.

## Proposal

1. `pmd render FILE --to text` **MUST** execute the same document scope as HTML
   rendering and emit a UTF-8 plain-text reader view.
2. The text view **MUST** include rendered narrative, stdout, errors, and rich
   Markdown/CSV output. Markdown table delimiter rows **MUST NOT** leak through.
3. The text view **MUST NOT** include the cell graph or executable source.
4. `--out` selects the destination; otherwise the target is `FILE.txt`.

## Alternatives considered

- **Strip tags with a regular expression.** Tables and preformatted blocks need
  structural handling; an HTML parser is both smaller and more reliable.
- **Return raw Markdown plus stdout.** That does not expose renderer failures,
  which is the purpose of this target.
