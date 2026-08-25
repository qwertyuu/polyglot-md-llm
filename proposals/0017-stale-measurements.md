# Proposal 0017: Staleness metadata for measurements

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 3.3
**Touches:** cell attributes, cache metadata, check and HTML rendering

## Motivation

Network and remote-machine measurements become obsolete even when their source
and declared inputs do not change. A cached successful result can therefore
remain technically reproducible while silently becoming unsuitable evidence
for a current decision.

## Proposal

1. Executable cells **MAY** declare `stale-after=<duration>` using `s`, `m`, `h`,
   or `d` units.
2. Successful cache entries **MUST** retain the original execution timestamp and
   a per-document freshness record tied to the cell source digest.
3. HTML **MUST** display measurement age and visibly mark results beyond their
   threshold.
4. `pmd check` **MUST** emit a warning for a matching last successful execution
   beyond the threshold. Missing history is reported as an advisory warning.

## Alternatives considered

- **Use file modification time.** Editing prose would make an old measurement
  appear fresh, while restoring a file could make a new measurement appear old.
- **Force re-execution automatically.** Staleness is evidence for a decision;
  network access and cost still require an explicit execution choice.
