# Proposal 0010: Actionable verification block reasons

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 1.4
**Touches:** `agent_protocol.py`, verification receipts and diagnostics

## Motivation

The runner records why a cell is blocked, but agent verification collapses that
information into a generic `policy_blocked` diagnostic. The receipt therefore
cannot tell an orchestrator whether to repair a dependency, change a request,
or ask for authorization.

## Proposal

1. Every blocked verification receipt **MUST** contain a non-empty `reason`.
2. The receipt **MUST** include structured `detail` when a cell caused the
   block, including its identifier and the runner's original message.
3. The `policy_blocked` diagnostic **MUST** carry the same detail and an
   actionable message. Existing diagnostic codes and exit codes remain stable.

## Alternatives considered

- **Only put the reason in the human message.** Agents should not have to parse
  prose when the information is already structured.
- **Add a new error code per blocking cause.** The current runner has few causes
  and can preserve compatibility by enriching the existing diagnostic first.
