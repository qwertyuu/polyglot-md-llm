# Proposal 0016: Bounded rendered cell inspection

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 3.1
**Touches:** agent inspect protocol, renderer, CLI authorization

## Motivation

The text render exposes a whole reader view, but an agent editing one cell also
needs a bounded view of that cell's rendered output. Producing it may execute
the selected dependency closure, so a read-looking command must not silently
cross the execution authorization boundary.

## Proposal

1. Inspect requests **MAY** set `include_rendered: true`; the CLI exposes this
   as `agent inspect --include-rendered`.
2. Rendered inspection **MUST** require `--allow-execution` and otherwise fail
   with `authorization_required` and exit code 5.
3. Each selected cell **MUST** receive a bounded `text/plain` `rendered` content
   object using the normal response-budget omission convention.
4. The rendered cell view **MUST NOT** include executable source.

## Alternatives considered

- **Execute implicitly.** This violates the agent protocol's fail-closed model.
- **Only return cached output.** Cache misses would make the feature unreliable
  and there is no current run snapshot contract to identify a preferred cache
  entry safely.
