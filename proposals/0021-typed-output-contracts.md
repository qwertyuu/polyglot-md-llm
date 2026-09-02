# Proposal 0021: Typed context output contracts

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 4.1
**Touches:** cell attributes, static graph validation, runner validation

## Motivation

`ctx` is machine-readable JSON but has no declared signature. Missing dependency
edges therefore surface as runtime `KeyError`, consumers must inspect source to
discover output keys, and notebooks cannot be composed safely.

## Proposal

1. A cell **MAY** declare `produces=KEY:schema#NAME`, comma-separated for
   multiple keys. Named schemas live under frontmatter `schemas`.
2. `check` **MUST** validate declaration syntax, schema references, duplicate
   producers, and literal `ctx` reads of a contract key whose producer is not
   in the cell's dependency closure.
3. A successful process **MUST** be changed to failed when it does not produce a
   declared key or the produced JSON value violates its schema.
4. The built-in validator covers JSON Schema `type`, `enum`, `required`,
   `properties`, `items`, and `additionalProperties`. Unsupported keywords are
   ignored for forward compatibility in this first version.

## Alternatives considered

- **Require a third-party JSON Schema package.** The supported core is small and
  keeping it built in avoids adding a large dependency to every PMD runtime.
- **Infer outputs from source.** `ctx.set` can be dynamic and inference cannot
  create a stable public contract.
