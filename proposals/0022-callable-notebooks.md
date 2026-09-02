# Proposal 0022: Callable notebooks

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 4.2
**Touches:** CLI composition over typed output contracts

## Motivation

Typed outputs give a notebook a discoverable result signature. A machine still
needs a stable invocation that injects JSON input and returns selected output
without parsing execution logs or notebook source.

## Proposal

1. `pmd call FILE --input JSON --output KEY` **MUST** execute the production
   graph with the input object as run-scoped context.
2. `--input -` reads JSON from stdin and `--input @PATH` reads a UTF-8 JSON file.
3. Requested keys **MUST** be declared by `produces` and present in a successful
   result. One output prints its JSON value; multiple outputs print a keyed JSON
   object.
4. Successful stdout **MUST** contain only the returned JSON. Execution warnings
   and errors use stderr.

## Alternatives considered

- **Return the entire final context.** Internal keys are not part of the public
  signature and would couple callers to implementation details.
- **Reuse `run --verbose`.** Human status lines are deliberately unsuitable as
  a machine-to-machine return channel.
