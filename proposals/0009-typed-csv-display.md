# Proposal 0009: Explicit `display.csv` input contract

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 1.3
**Touches:** Python bindings, CSV rich-output conformance

## Motivation

`display.csv()` currently stringifies every value. A mapping therefore passes
execution and creates invalid CSV, while a list of row mappings creates a
single unreadable cell. Silent coercion is especially harmful in a document
pipeline because the failure appears only in the rendered artifact.

## Proposal

1. `display.csv(value, name)` **MUST** accept CSV text unchanged.
2. It **MUST** accept a list of dictionaries and serialize it with a header.
   Columns **MUST** follow first appearance order across the rows.
3. Other values, including a dictionary that is not wrapped in a list, **MUST**
   raise `TypeError` with a message naming the accepted forms.

## Alternatives considered

- **Accept every iterable.** Rows, headers, scalar coercion, and generators all
  introduce ambiguous behavior. Those forms can be added later with an
  explicit contract.
- **Only improve documentation.** That leaves the dangerous success mode in
  place and gives agents no runtime signal to repair.
