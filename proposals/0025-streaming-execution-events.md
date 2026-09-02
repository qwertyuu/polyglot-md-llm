# Proposal 0025: Streaming execution events

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 4.5
**Touches:** runner callbacks and agent NDJSON CLI

## Motivation

An agent supervising a long notebook cannot react until the full run returns.
Jupyter's messaging protocol is unnecessary for PMD's isolated cell processes;
a small ordered event stream is enough.

## Proposal

1. `pmd agent run FILE --stream --allow-execution` **MUST** emit UTF-8 NDJSON.
2. The stream **MUST** contain `run_started`, paired `cell_started` and
   `cell_finished` events, then `run_finished`.
3. Finished-cell events **MUST** include status, source digest, output byte
   counts/digests, attachments, timestamp, and duration when known.
4. Streaming agent execution **MUST** fail closed without explicit host
   authorization.

## Alternatives considered

- **Buffer JSON until completion.** That preserves the existing envelope but
  does not permit supervision or early reaction.
- **Adopt Jupyter messaging.** Kernels, channels, and session state conflict
  with PMD's process-per-cell model and add no value for ordered events.
