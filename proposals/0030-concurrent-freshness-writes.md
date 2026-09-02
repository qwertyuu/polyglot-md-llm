# Proposal 0030: Retry concurrent freshness-registry writes

**Status:** Implemented (next patch release)
**Fixes:** Concurrent runs can fail while replacing `stale-after` metadata on Windows
**Touches:** cache persistence and measurement freshness

## Motivation

Two runs of the same notebook can finish the same measurement cell at nearly
the same time. Windows may transiently deny one atomic replacement of the
shared freshness record. That metadata race currently escapes from cache
storage and turns a successfully executed cell into a CLI traceback.

## Proposal

1. Cache and freshness JSON writes **MUST** use a unique temporary file for
   each write attempt.
2. A transient `PermissionError` during atomic replacement **SHOULD** be retried
   with a short bounded backoff.
3. Temporary files **MUST** be removed after success or terminal failure.
4. A regression test **MUST** inject a transient replacement denial and confirm
   that the run succeeds with a readable freshness record.

## Alternatives considered

- **Ignore all freshness write errors.** Losing measurement age silently would
  make `stale-after` unreliable.
- **Use a process-wide lock.** It cannot coordinate independent PMD processes,
  which is the observed failure mode.
- **Serialize whole notebook runs.** Independent runs and agents should remain
  able to execute concurrently.
