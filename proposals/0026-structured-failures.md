# Proposal 0026: Structured execution failures

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 4.6
**Touches:** result model, runner, verification diagnostics and event stream

## Motivation

Agents currently parse traceback strings to identify an exception, cell line,
and relevant context. Binding preambles shift interpreter line numbers, making
that repair loop especially fragile.

## Proposal

1. Failed and blocked `CellResult` objects **MUST** include a structured failure
   with cell id, language, kind, message, exit code, and resolved input context.
2. Python failures **SHOULD** include exception type, cell-relative line number,
   and the corresponding source line when recoverable.
3. Verification diagnostics, receipt cell evidence, and streaming
   `cell_finished` events **MUST** propagate the structured object.
4. Traceback text remains available in stderr for humans and compatibility.

## Alternatives considered

- **Parse tracebacks only in clients.** Every client would repeat an
  engine-specific, binding-offset-sensitive parser.
- **Remove tracebacks after structuring.** Structured extraction can be
  incomplete; retaining native stderr preserves full diagnostic evidence.
