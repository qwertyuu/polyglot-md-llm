# Proposal 0024: Interpreter-bound provenance attestations

**Status:** Implemented (0.6.0)
**Fixes:** PMD 0.5.0 field report section 4.4
**Touches:** cache identity, verification receipts, attestation CLI

## Motivation

A receipt links source, inputs, and outputs but cannot support cross-machine
provenance if an unchanged engine command resolves to a different interpreter
version. The receipt also lacks a standard envelope for audit tooling.

## Proposal

1. Cell cache keys **MUST** include the resolved executable path, its version
   response when available, and file identity metadata.
2. Verification plans and cell evidence **MUST** expose the same engine identity.
3. `pmd attest FILE --receipt JSON` **MUST** accept only a verified receipt bound
   to the current document revision and emit an in-toto Statement using the
   SLSA provenance predicate type.
4. The first implementation emits an unsigned statement. It **MUST NOT** claim
   cryptographic authenticity; signing can wrap the canonical JSON later.

## Alternatives considered

- **Use the command string as engine identity.** A stable path such as `python`
  can resolve to materially different runtimes across machines or upgrades.
- **Invent a PMD-only attestation format.** in-toto/SLSA provides established
  subject and provenance vocabulary without changing the underlying receipt.
