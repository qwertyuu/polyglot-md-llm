# Proposal 0029: Preserve cache-key integrity during typed-output validation

**Status:** Implemented (next patch release)
**Fixes:** `produces=` output names overwrite the computed cache key
**Touches:** typed output validation, cache storage, verification receipts

## Motivation

Typed-output validation reused the local variable named `key` while iterating
declared output names. A successful `produces=totaux:...` cell could therefore
store and report `totaux` as its cache key instead of the previously computed
SHA-256 digest. This defeats cache isolation and weakens receipt evidence.

## Proposal

1. Output-contract validation **MUST NOT** mutate the computed execution cache
   key.
2. Successful typed-output cells **MUST** store results under the same digest
   reported by their `CellResult` and verification receipt.
3. A regression test **MUST** execute a typed-output cell, assert a full digest,
   and recover the result from that cache entry on a subsequent run.

## Alternatives considered

- **Disable caching for typed outputs.** Typed validation is deterministic over
  the produced context and schema; disabling reuse would hide rather than fix
  the state corruption.
- **Recompute the key after validation.** The original digest is already valid;
  preserving it avoids duplicate engine probes and hashing work.
