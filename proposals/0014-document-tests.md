# Proposal 0014: Tests over the rendered document

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 3.2
**Touches:** parser, Python binding, runner, test conformance

## Motivation

Cell tests validate computation but cannot detect document defects such as raw
table syntax, missing terminology, or malformed reader output. The rendered
document is the deliverable and needs a first-class test target.

## Proposal

1. `role=test test-of=document` **MUST** designate a document-level test and
   depend on every executable non-test cell.
2. Python document tests **MUST** receive the reader-visible text as
   `rendered.text` without causing a second execution of the notebook.
3. The digest of that reader view **MUST** participate in the test cache key.
4. Normal `test-of=<cell-id>` behavior remains unchanged.

## Alternatives considered

- **Put rendered text in `ctx`.** This leaks an implementation value into normal
  notebook data flow and risks collisions with author keys.
- **Render after tests.** A test cannot inspect an artifact that does not yet
  exist; rendering from already collected results preserves process isolation.
