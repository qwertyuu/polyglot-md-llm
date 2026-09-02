# Proposal 0020: Named narrative sections

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 3.7
**Touches:** agent narrative segmentation and semantic editing

## Motivation

Narrative currently exists only as the entire interval between two cells. A
single interval can span the conclusion of one section and the request in the
next, so targeting `before:cell` is concurrency-safe but too coarse in scope.

## Proposal

1. Agent narrative discovery **MUST** split intervals at Markdown ATX headings.
2. A heading and its following prose **MUST** receive a stable
   `section:<slug>` segment id. Duplicate slugs receive document-order suffixes.
3. Prose before the first heading in an interval retains the existing
   `before:<cell>` or `after:last` identity.
4. `replace_narrative` **MUST** accept named section ids with the same digest
   precondition and atomicity guarantees as existing segments.

## Alternatives considered

- **Require explicit anchor syntax.** Explicit anchors can be added later, but
  existing literary documents already contain headings that provide useful,
  human-readable identities.
- **Change segment ids to heading line numbers.** Line numbers are unstable
  under unrelated prose edits and poor semantic handles for agents.
