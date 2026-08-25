# Proposal 0008: Render fidelity for preformatted output and Markdown tables

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report sections 1.1 and 1.2
**Touches:** `render.py`, HTML rendering conformance

## Motivation

The HTML renderer is the delivered document, but two common authoring forms do
not survive that boundary faithfully. Captured stdout inherits the document's
proportional body font, destroying column alignment that is correct in a
terminal. GFM-style pipe tables in narrative or `display.markdown()` are left
as literal text inside a paragraph.

Both failures are easy to miss during `run --verbose` and only become visible
after rendering, so they can escape otherwise successful execution and tests.

## Proposal

1. Captured stdout and stderr in HTML **MUST** use the renderer's monospace font
   stack. A component rule **MUST NOT** reset those blocks to the proportional
   body font.
2. The Markdown renderer **MUST** enable pipe-table syntax for both narrative
   Markdown and Markdown rich outputs.
3. Rendered tables **MUST** retain semantic `<table>`, `<thead>`, `<tbody>`,
   `<th>`, and `<td>` elements so machine and accessibility tooling can inspect
   their structure.

## Alternatives considered

- **Ask authors to emit CSV instead.** Narrative tables remain a normal part of
  literary Markdown, and this does not address existing documents.
- **Preserve pipe tables as preformatted text.** This keeps alignment but loses
  table semantics and does not match common Markdown expectations.
