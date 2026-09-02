# Proposal 0012: Narrative replacement evidence

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 1.6
**Touches:** `agent_protocol.py`, `apply` response schema

## Motivation

A narrative segment spans everything between two cells and can contain several
sections. Digest preconditions prevent concurrent overwrites but do not reveal
the scope that was replaced. An apparently local `before:cell` edit can
therefore remove unrelated prose without a clear signal in the structured
response.

## Proposal

1. `agent apply` **MUST** return one `replaced_narrative` evidence object for
   each `replace_narrative` operation.
2. Evidence **MUST** identify both adjacent cells and include the previous text,
   digest, media type, and byte count.
3. Under a tight response budget, the previous text **MAY** be omitted using the
   existing bounded-content convention, but its digest and size **MUST** remain.

## Alternatives considered

- **Split narrative automatically at headings.** Named narrative anchors are a
  useful later feature, but changing segment identity requires a broader agent
  protocol design.
- **Rely only on the unified diff.** Diffs can be omitted for budget and require
  textual reconstruction; explicit evidence is safer for machine clients.
