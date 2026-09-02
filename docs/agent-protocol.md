# PMD Agent Protocol Specification

**Specification - Draft v0.1**  
**Status:** Draft companion specification for PMD 0.1.  
**Protocol identifier:** `pmd-agent/0.2`

This specification defines the machine interface that makes a PMD document
safe and efficient for a language-model agent to inspect, edit, execute, and
verify. It does not change the `.pmd` source format. A document remains plain
Markdown and continues to follow the [core PMD specification](spec.md).

The central contract is:

> An agent can make a scoped notebook change and obtain machine-checkable
> evidence about its impact without reading, rewriting, or executing unrelated
> parts of the document.

## 0. Conformance language

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **SHOULD NOT**,
and **MAY** are to be interpreted as described in RFC 2119.

Examples are non-normative unless explicitly identified as normative.

## 1. Scope

### 1.1 Problems addressed

The protocol standardizes five operations needed by an automated coding agent:

1. Discover runner capabilities without parsing human-oriented help text.
2. Inspect a bounded semantic neighborhood of a notebook.
3. Change cells and narrative through atomic semantic operations.
4. Compute the execution and test impact of a change.
5. Return structured evidence tying verification results to one exact document
   revision.

### 1.2 Meaning of LLM-ready

An implementation **MUST NOT** describe itself as "PMD LLM-ready" unless it
implements the complete conformance profile in section 3. Plain-text storage,
JSON serialization, or the ability to invoke an LLM is not sufficient.

"LLM-ready" does not mean that notebook content is trusted, that generated
changes are correct, or that arbitrary code is safe to execute.

### 1.3 Non-goals

This protocol does not:

- Define a model provider, prompt format, agent loop, or tool-call transport.
- Require notebook content to fit in a model context window.
- Treat test success as proof of semantic correctness.
- Grant a document or agent permission to execute code.
- Mandate a particular sandbox implementation.
- Store model conversations, chain-of-thought, or credentials in the document.
- Replace the human-oriented PMD CLI.

## 2. Design principles

### 2.1 Semantic addressing

Cells are addressed by stable PMD cell IDs, never by array indexes or line
numbers. Narrative segments use revision-scoped IDs supplied by `inspect`.

### 2.2 Bounded context

An agent must be able to request only the selected cells, their nearby graph
relationships, associated tests, and adjacent narrative. Every potentially
large response field must support explicit omission under a byte budget.

### 2.3 Optimistic concurrency

Every mutating request names the exact document revision it was based on. A
runner must reject a stale request instead of applying it to changed content.

### 2.4 Structural preservation

Semantic edits preserve bytes unrelated to the requested operations. An agent
does not need to regenerate a complete Markdown document to change one cell.

### 2.5 Validation before execution

Inspection and editing never execute notebook code. A mutation is committed
only if the resulting document parses and passes static PMD validation.

### 2.6 Evidence, not confidence

Verification reports what was checked, what ran, what was cached, what was
blocked, and what remains unverified. It does not return a model-generated
confidence score.

### 2.7 Host authority

Notebook metadata and agent requests may reduce authority but can never grant
authority beyond host policy. Execution authorization comes from the host or
human operator, not from content inside the notebook.

## 3. Conformance

### 3.1 Component profiles

An implementation may advertise these component profiles:

| Profile | Required commands | Purpose |
|---|---|---|
| `reader` | `capabilities`, `inspect` | Bounded machine-readable understanding. |
| `editor` | `apply` | Atomic semantic changes. |
| `verifier` | `verify` | Impact-scoped execution and evidence. |

### 3.2 LLM-ready profile

The `llm-ready` profile **MUST** implement all three component profiles. It
**MUST** also implement:

- Document revision preconditions from section 6.
- Deterministic JSON responses from section 5.
- The minimum mutation set in section 9.3.
- Impact analysis from section 10.
- Verification receipts from section 12.
- Secret redaction and untrusted-content labeling from section 14.

An implementation **MUST** advertise `llm-ready` only when all these
requirements are available in the runner and active host configuration.

### 3.3 Capability degradation

Unavailable optional behavior must be reported as a missing capability. A
runner **MUST NOT** silently substitute a weaker behavior. For example, a
runner unable to enforce a requested network denial must block verification or
report the restriction as unenforced; it must not mark the run verified under
that restriction.

## 4. Terminology

| Term | Meaning |
|---|---|
| **Agent client** | A program operating PMD through this protocol. It may or may not contain an LLM. |
| **Document revision** | A SHA-256 digest of the exact `.pmd` file bytes. |
| **Semantic neighborhood** | Selected cells plus requested upstream, downstream, test, and narrative relationships. |
| **Mutation transaction** | An ordered list of semantic edits applied atomically to one document revision. |
| **Directly changed cell** | A cell whose source, language, role, attributes, identity, or position was changed by a transaction. |
| **Affected cell** | A directly changed executable cell or any executable cell transitively downstream from it. |
| **Impacted test** | A test whose target or dependency closure intersects the affected cells. |
| **Verification plan** | The exact cells, tests, inputs, policy, and execution options proposed for verification. |
| **Verification receipt** | Structured evidence describing a completed, failed, blocked, or incomplete verification plan. |
| **Host policy** | Execution restrictions supplied outside the notebook by the user, agent host, CI system, or runner configuration. |
| **Document policy** | Restrictions requested by notebook frontmatter. A document policy is untrusted and may only narrow host policy. |

## 5. Protocol transport and envelopes

### 5.1 Required CLI transport

A conforming CLI exposes:

```text
pmd agent capabilities
pmd agent inspect FILE [--request PATH|-]
pmd agent apply FILE --request PATH|-
pmd agent verify FILE --request PATH|- [--allow-execution]
pmd agent run FILE --stream --allow-execution
```

`-` means UTF-8 JSON read from standard input. Implementations may additionally
provide a library API, MCP server, HTTP API, or editor protocol, but those
transports must preserve the semantics and data model defined here.

### 5.2 Standard output

Except for `agent run --stream`, an agent command **MUST** write exactly one
UTF-8 JSON object to stdout. Streaming run writes one JSON object per line in
event order (NDJSON). Agent stdout **MUST NOT** mix progress indicators,
warnings, logs, or ANSI control sequences. Human-readable diagnostics may be
written to stderr.

Object keys **MUST** be emitted in a deterministic order, and arrays whose order
is not otherwise meaningful **MUST** use document order followed by lexical
order as a tie-breaker.

### 5.3 Common response envelope

Every response has these fields:

```json
{
  "protocol": "pmd-agent/0.2",
  "command": "inspect",
  "ok": true,
  "document": {
    "path": "analysis.pmd",
    "revision": "sha256:..."
  },
  "warnings": [],
  "errors": [],
  "result": {}
}
```

Required envelope fields:

| Field | Type | Meaning |
|---|---|---|
| `protocol` | string | Exact protocol version used for the response. |
| `command` | string | Agent command that produced the response. |
| `ok` | boolean | Whether the requested protocol operation completed successfully. |
| `document` | object or null | Canonical path and revision when a document was resolved. |
| `warnings` | array | Structured non-fatal diagnostics. |
| `errors` | array | Structured fatal diagnostics. Empty when `ok` is true. |
| `result` | object or null | Command-specific result. Null when no result is available. |

Paths in protocol responses **MUST** use `/` separators. A runner **SHOULD**
return document-relative paths when possible and **MUST NOT** expose temporary
cache paths unless explicitly requested.

### 5.4 Diagnostics

Each warning or error has this minimum shape:

```json
{
  "code": "revision_conflict",
  "message": "document changed after inspection",
  "cell_id": null,
  "operation_index": null,
  "details": {}
}
```

Clients must branch on `code`, not on `message`. Messages are intended for
humans and are not stable API values.

Required error codes are defined in section 13.

### 5.5 Exit codes

| Code | Meaning |
|---|---|
| `0` | Protocol operation succeeded. For `verify`, the result is `verified`. |
| `1` | Verification executed but failed. |
| `2` | Invalid PMD document or invalid protocol request. |
| `3` | CLI usage error. |
| `4` | Revision or operation precondition conflict. |
| `5` | Execution was not authorized or was blocked by policy/capability. |
| `6` | Runner internal error. |

The JSON envelope is required even for nonzero exits when the agent command was
recognized. Failures before command recognition may use the normal PMD usage
surface.

## 6. Document revisions and digests

### 6.1 Document revision

The document revision is:

```text
"sha256:" + lowercase_hex(SHA256(exact_file_bytes))
```

No newline normalization, Unicode normalization, frontmatter normalization, or
Markdown parsing occurs before hashing.

### 6.2 Content digests

Cell source, narrative, external inputs, outputs, and execution artifacts use
the same `sha256:` representation. The response must state whether a digest
covers raw bytes, decoded text, or a canonical JSON value. Canonical JSON uses
UTF-8, sorted object keys, no insignificant whitespace, and JSON number and
string syntax.

### 6.3 Mutation precondition

Every `apply` request **MUST** contain `base_revision`. Immediately before
writing, the runner **MUST** hash the file again. If it differs from
`base_revision`, the runner must return `revision_conflict`, perform no write,
and exit `4`.

### 6.4 Verification precondition

Every `verify` request **MUST** contain `document_revision`. The runner must
reject a different current revision before creating processes or changing the
cache.

## 7. Capability discovery

### 7.1 Command

`pmd agent capabilities` does not read or execute a notebook. It returns the
protocol versions, profiles, operations, limits, engines, and enforceable
policy features supported by the runner.

Minimum result:

```json
{
  "protocol_versions": ["pmd-agent/0.2", "pmd-agent/0.1"],
  "profiles": ["reader", "editor", "verifier", "llm-ready"],
  "operations": [
    "replace_cell_source",
    "insert_cell",
    "delete_cell",
    "rename_cell",
    "set_cell_language",
    "set_cell_attributes",
    "move_cell",
    "replace_narrative",
    "replace_frontmatter"
  ],
  "limits": {
    "max_request_bytes": 1048576,
    "max_response_bytes": 1048576,
    "change_token_lifetime_seconds": 86400
  },
  "policy_enforcement": {
    "network": false,
    "filesystem": false,
    "environment": true,
    "runtime": true
  }
}
```

Capability discovery describes what can be enforced, not what is authorized
for a particular invocation.

## 8. Bounded semantic inspection

### 8.1 Command

`pmd agent inspect FILE` parses and validates the document without execution by
default. `include_rendered: true` requires an explicit `--allow-execution`
because producing a missing render may execute the selected closure. Its
request object selects a semantic neighborhood and content budget.

Example request:

```json
{
  "roots": ["compute"],
  "upstream_depth": 1,
  "downstream_depth": 1,
  "include_tests": true,
  "include_source": true,
  "include_rendered": false,
  "include_narrative": "adjacent",
  "include_frontmatter": true,
  "max_bytes": 65536
}
```

### 8.2 Selection

- `roots` is an array of cell IDs. An empty or omitted array selects all cells
  for metadata, subject to the response budget.
- `upstream_depth` and `downstream_depth` are non-negative integers. `0` means
  no traversal in that direction.
- `include_tests` includes tests whose `test-of` target or explicit dependency
  appears in the selected neighborhood.
- `include_narrative` is `none`, `adjacent`, or `all`.
- `include_source` controls source text, not cell metadata.
- `include_rendered` adds a bounded `text/plain` reader view per selected cell,
  excluding executable source, and requires host execution authorization.
- When `include_frontmatter` is true, the result includes parsed frontmatter
  metadata and its complete bounded source representation, excluding `---`
  delimiters.
- `max_bytes` is a hard maximum for the UTF-8 encoded JSON response. The runner
  may impose and advertise a lower implementation maximum.

Unknown roots or invalid depths are request errors. Inspection never silently
widens graph depth to fill spare budget.

### 8.3 Cell representation

Each selected cell includes at least:

```json
{
  "id": "compute",
  "language": "python",
  "role": "code",
  "position": 2,
  "attributes": {
    "depends-on": "fetch"
  },
  "dependencies": {
    "explicit": ["fetch"],
    "resolved": ["fetch"]
  },
  "uses": [],
  "upstream": ["fetch"],
  "downstream": ["report", "test-compute"],
  "tests": ["test-compute"],
  "source": {
    "included": true,
    "media_type": "text/x-python",
    "bytes": 184,
    "digest": "sha256:...",
    "text": "..."
  },
  "rendered": null,
  "content_trust": "untrusted"
}
```

`position` is informative and revision-scoped. It must not be used as an edit
identity. `dependencies.explicit` distinguishes authored dependencies from the
implicit sequential dependency resolved by the PMD core specification.

### 8.4 Narrative representation

Narrative is returned as source spans between frontmatter and cells, split at
Markdown ATX headings. Heading sections receive stable `section:<slug>` IDs;
interstitial prose retains `before:<cell>` / `after:last` IDs.
Each span receives a revision-scoped ID, digest, location relationship, and the
same bounded-content representation used for source:

```json
{
  "segment_id": "before:compute",
  "digest": "sha256:...",
  "before_cell": "compute",
  "after_cell": "fetch",
  "content": {
    "included": true,
    "media_type": "text/markdown",
    "bytes": 92,
    "digest": "sha256:...",
    "text": "## Compute\n\nSummarize the fetched rows.\n"
  },
  "content_trust": "untrusted"
}
```

Narrative IDs are valid only with the document revision returned by the same
inspection. An implementation must not imply that they are stable across
edits.

### 8.5 Bounded content

Potentially large content uses one of these two shapes:

```json
{
  "included": true,
  "bytes": 184,
  "digest": "sha256:...",
  "text": "complete content"
}
```

```json
{
  "included": false,
  "bytes": 918420,
  "digest": "sha256:...",
  "reason": "response_budget"
}
```

A runner **MUST NOT** silently truncate content strings. It may omit a complete
field and return its size and digest. The response must include an `omissions`
array listing every requested item not included and why.

If the envelope and mandatory metadata alone exceed `max_bytes`, inspection
must fail with `response_budget_too_small` rather than emit invalid or oversized
JSON.

### 8.6 Validation and status metadata

Inspection returns all static PMD diagnostics. It should additionally return,
when locally available without execution:

- Whether each cell has a cache entry for the current source and inputs.
- Whether a cached result is fresh, stale, or indeterminate.
- Output names, media types, sizes, and digests without embedding output bytes.
- The most recent execution status and receipt ID.

Cached notebook content remains `untrusted`.

## 9. Atomic semantic mutation

### 9.1 Command

`pmd agent apply FILE --request PATH|-` applies an ordered mutation transaction.
It never executes notebook cells.

Example request:

```json
{
  "base_revision": "sha256:...",
  "dry_run": false,
  "max_response_bytes": 65536,
  "operations": [
    {
      "op": "replace_cell_source",
      "cell_id": "compute",
      "expected_source_digest": "sha256:...",
      "source": "total = sum(rows)\nctx.set(\"total\", total)\n"
    }
  ]
}
```

### 9.2 Transaction rules

The runner must:

1. Verify `base_revision`.
2. Parse and statically validate the original document.
3. Apply operations in request order to an in-memory representation.
4. Serialize the candidate while preserving unrelated source bytes.
5. Parse and statically validate the complete candidate document.
6. If `dry_run` is false, atomically replace the file.
7. Return the candidate revision, normalized operation results, a bounded
   unified diff, impact analysis, and recommended verification request.

If any operation or validation fails, no file bytes may change. An atomic
replace must not expose a partially written document to another process.

Operations are evaluated against the evolving transaction. A later operation
may refer to a cell inserted or renamed by an earlier operation.

### 9.3 Required operations

#### `replace_cell_source`

Required fields: `cell_id`, `expected_source_digest`, `source`.

Only the cell source is semantically changed. The runner may lengthen or change
the surrounding Markdown fence when necessary to contain the new source. It
must preserve the cell language, ID, attributes, relative position, and all
unrelated bytes.

#### `insert_cell`

Required fields: `cell_id`, `language`, `source`, and exactly one placement:
`before`, `after`, or `at_end`. Optional `attributes` uses PMD attribute names
without `#id`.

The runner chooses a valid fence and serialization. It must reject an existing
ID and any insertion that makes the PMD graph invalid.

#### `delete_cell`

Required fields: `cell_id`, `expected_source_digest`.

Deletion removes the cell fence and source, but not surrounding narrative.
Deletion must fail with `dependent_cells_exist` if another remaining cell
references the ID after all transaction operations are applied. There is no
implicit cascade deletion.

#### `rename_cell`

Required fields: `cell_id`, `new_cell_id`.

The runner atomically changes the ID and all `depends-on` and `test-of`
references in the same document. It must reject an invalid or existing ID.

#### `set_cell_language`

Required fields: `cell_id`, `language`.

The runner changes the code-fence language without changing source or
attributes. The resulting language must resolve to a known engine or the
transaction fails static validation.

#### `set_cell_attributes`

Required fields: `cell_id`, `set`, `remove`.

`set` is an object of attribute names to string values. `remove` is an array of
attribute names. The ID is not an attribute for this operation. The runner must
reject unknown attributes and contradictory set/remove entries.

#### `move_cell`

Required fields: `cell_id` and exactly one of `before`, `after`, or `at_end`.

Moving a cell moves only its complete fence. Narrative remains in place. Since
document order can change implicit dependencies, the response must show both
the old and new resolved dependency graph for every cell whose dependencies
changed.

#### `replace_narrative`

Required fields: `segment_id`, `expected_digest`, `markdown`.

`segment_id` must come from an inspection of `base_revision`. This operation
replaces the complete narrative span and must not create an executable cell
unless that cell is also represented by an explicit `insert_cell` operation.
The apply response includes bounded `replaced_narrative` evidence with the old
content, digest, and adjacent cell IDs for every such operation.

#### `replace_frontmatter`

Required fields: `expected_digest`, `yaml`.

`yaml` contains the complete YAML source between frontmatter delimiters. The
runner preserves the existing delimiters and document newline convention. If
the document has no frontmatter, `expected_digest` must be null and the runner
inserts a frontmatter block at the beginning. An empty `yaml` value removes the
frontmatter block. The parsed value must be a mapping and the complete candidate
must pass PMD validation.

### 9.4 Per-operation preconditions

Expected digests protect against mistakes inside a transaction and are required
where specified even though the request also has a document revision. A digest
mismatch returns `operation_precondition_failed` with the operation index.

### 9.5 Preservation requirements

Except for byte spans necessarily affected by successful operations, a runner
must preserve:

- Original newline convention.
- UTF-8 byte order mark, if present.
- Frontmatter formatting and key order.
- Fence character and length when still valid.
- Attribute order and quoting when untouched.
- Whitespace and narrative content.

The response must list any normalization it performed. An empty list means the
candidate differs only in operation-requested spans and necessary fence edits.

### 9.6 Apply result

The result includes:

```json
{
  "applied": true,
  "dry_run": false,
  "base_revision": "sha256:...",
  "new_revision": "sha256:...",
  "change_token": "opaque-runner-token",
  "changed_cells": ["compute"],
  "changed_narrative": [],
  "normalizations": [],
  "diff": {
    "included": true,
    "bytes": 241,
    "digest": "sha256:...",
    "text": "..."
  },
  "impact": {},
  "recommended_verification": {}
}
```

For `dry_run`, `applied` is false and `new_revision` is the digest the candidate
would have if written. `change_token` is null for a dry run.

`max_response_bytes` defaults to the runner's advertised maximum. The diff uses
the bounded-content representation from section 8.5 and may be omitted with a
size, digest, and reason. Operation results, impact metadata, and recommended
verification are mandatory and must not be silently truncated.

For a committed transaction, `change_token` is an opaque, unguessable handle to
the runner's transaction record. The record binds the base revision, new
revision, normalized operations, and impact result. An `llm-ready` runner must
accept that token in a later `verify` request until the first of:

- The document is changed again through the same runner.
- The runner's advertised token lifetime expires.
- The transaction record is explicitly removed by the host.

The token must not encode notebook content or secrets in plaintext. Possession
of a token identifies change scope but does not authorize execution.

## 10. Impact analysis

### 10.1 Purpose

Impact analysis determines the minimum scope that must be considered after a
transaction. It is structural, deterministic, and does not inspect language
semantics.

### 10.2 Cell impact

The impact result reports these related sets:

- `directly_changed`: source, language, role, attributes, identity, or position
  changed.
- `dependency_changed`: resolved dependencies changed, including changes caused
  by moving cells with implicit sequential dependencies.
- `affected`: executable directly changed or dependency-changed cells plus all
  transitively downstream executable cells.
- `impacted_tests`: directly changed tests plus tests whose target or dependency
  closure intersects `affected`.
- `unaffected`: all other cells.

For executable cells, `affected` and `unaffected` are disjoint and exhaustive.
`directly_changed` and `dependency_changed` explain why cells entered the
affected set and may overlap it. Tests are classified separately.

### 10.3 Document-wide impact

A change to any of the following makes all executable cells affected and all
tests impacted unless the runner can prove a narrower scope:

- Engine commands or engine resolution.
- Declared external inputs.
- Context backend semantics.
- Default timeout when it changes actual execution.
- PMD version.
- Execution policy or environment declarations.

Changing only title, narrative, or rendering metadata requires static
validation but no cell execution. If the implementation cannot distinguish
rendering metadata from execution metadata, it must conservatively report
document-wide impact.

### 10.4 Limit of impact claims

PMD permits filesystem and external-system access that may not be declared in
the graph. Impact analysis must include:

```json
{
  "confidence": "structural",
  "undeclared_state_possible": true,
  "reasons": ["host_filesystem_visible", "network_access_not_enforced"]
}
```

The protocol must not describe structural impact as complete semantic impact
when undeclared state is observable.

## 11. Verification

### 11.1 Command

`pmd agent verify FILE --request PATH|- --allow-execution` validates and
executes an impact-scoped plan. Without `--allow-execution`, it returns the plan
and a `blocked` receipt with error code `authorization_required`, starts no
process, and exits `5`.

The explicit execution flag may be replaced by an equivalent authorization in
a non-CLI transport. Notebook content, document frontmatter, and the request
body are not equivalent authorization. An agent host must prevent an untrusted
agent from manufacturing the authorization signal. If an agent already has
unrestricted shell access, the CLI flag is not an additional security boundary.

### 11.2 Request

```json
{
  "document_revision": "sha256:...",
  "change_token": "opaque-runner-token",
  "include_downstream": true,
  "tests": "impacted",
  "fresh": false,
  "render": false,
  "max_response_bytes": 262144,
  "limits": {
    "max_cells": 20,
    "max_runtime_seconds": 300,
    "max_output_bytes": 10485760
  },
  "restrictions": {
    "network": "deny",
    "environment_allow": ["SALES_API_TOKEN"]
  }
}
```

`tests` is `none`, `impacted`, or `all`. `impacted` is the default and is
required for the `llm-ready` profile unless there are no impacted tests.

The request must contain exactly one of `change_token` or `changed_cells`. It
should use the token in the `recommended_verification` object returned by
`apply`. A valid token makes the change scope runner-derived. `changed_cells`
is available for documents changed outside the semantic editor; the receipt
must then state that the scope was caller-asserted.

`restrictions` can only narrow execution. Host policy is supplied out of band
through trusted runner configuration or invocation context and cannot be
declared by request JSON.

`max_response_bytes` defaults to the runner's advertised maximum. Receipt
streams and output bodies are omitted before mandatory evidence. If the
mandatory plan, receipt, and diagnostic metadata cannot fit, the runner returns
`response_budget_too_small`; it must not emit a partial receipt.

### 11.3 Plan construction

The runner must build a deterministic plan containing:

- Current document revision.
- Selected changed, affected, dependency, and test cells.
- Execution order and cache eligibility.
- Engine command identity for every planned cell.
- Declared external input paths and current digests.
- Effective execution policy and enforcement support.
- Limits and reasons any requested work would be omitted.

The plan ID is the digest of its canonical JSON representation excluding the
plan ID field itself.

### 11.4 Minimum execution

When `include_downstream` is true, the runner executes every affected
`code`/`setup` cell and its required dependency closure, followed by impacted
tests. Valid cached results may satisfy unchanged dependencies unless `fresh`
is true. Directly changed and affected target cells may not be satisfied only
from a pre-change cache entry.

When `include_downstream` is false, the result must be `incomplete` unless the
changed cells have no downstream executable cells.

Skipped affected cells, unavailable engines, unenforced required restrictions,
exceeded limits, or omitted impacted tests prevent a `verified` result.

### 11.5 Verification result states

| State | Meaning |
|---|---|
| `verified` | Every item in the complete plan ran or was validly cached, all required tests passed, and no required policy or scope item was omitted. |
| `failed` | A cell or test executed and failed, or post-run static/output validation failed. |
| `blocked` | Execution did not complete because authorization, policy, capability, engine, or required input was unavailable. |
| `incomplete` | The requested scope deliberately omitted known affected work or tests. |

`verified` means verified against the stated plan. It is not proof that the
notebook is correct, deterministic, free of undeclared inputs, or safe.

### 11.6 Race detection

The runner must verify the document revision immediately before the first
process starts and immediately after the last process exits. If the file
changes during verification, the result cannot be `verified`. It must be
`blocked` with `document_changed_during_verification` and preserve the observed
results as non-authoritative diagnostics.

Declared external inputs must be fingerprinted when planning and again before
their first consumer executes. A changed input invalidates the plan.

## 12. Verification receipts

### 12.1 Required receipt

Every verification attempt returns a receipt, including attempts that are
blocked before execution.

Minimum shape:

```json
{
  "receipt_version": "pmd-verification/0.1",
  "receipt_id": "sha256:...",
  "status": "verified",
  "reason": null,
  "detail": {},
  "document_revision": "sha256:...",
  "plan_id": "sha256:...",
  "scope_source": "apply_transaction",
  "runner": {
    "name": "polyglot-pmd",
    "version": "0.2.0"
  },
  "started_at": "2026-08-08T20:15:00Z",
  "finished_at": "2026-08-08T20:15:04Z",
  "policy": {},
  "inputs": [],
  "cells": [],
  "tests": [],
  "omissions": [],
  "claims": {
    "static_validation": true,
    "planned_scope_complete": true,
    "declared_inputs_unchanged": true,
    "undeclared_state_possible": true
  }
}
```

The receipt ID is the digest of canonical receipt JSON excluding
`receipt_id`. A digest provides integrity correlation, not signer authenticity.

### 12.2 Cell evidence

Each planned cell entry includes:

- Cell ID, role, language, and source digest.
- Resolved dependency IDs and their result digests.
- Resolved engine command with secret values redacted.
- Resolved engine executable path, version response, and file identity.
- Status: `passed`, `failed`, `cached`, `blocked`, or `skipped`.
- Whether a cache entry was used and its cache key.
- Start time, duration, exit code, and expected exit code.
- Complete stdout and stderr byte counts and digests.
- Rich output names, media types, byte counts, and digests.
- Context delta key names and canonical value digests.
- Structured failure details for failed/blocked cells, including cell-relative
  location and resolved input context when available.

Receipt output does not need to embed full streams, outputs, or context values.
If included, they remain untrusted content and count toward the response budget.

### 12.3 Test evidence

Tests include their `test-of` target, dependency closure, status, and the same
execution evidence as other cells. The receipt must distinguish tests that do
not exist from tests that exist but were omitted.

### 12.4 Storage

A runner may store receipts outside the `.pmd` source. Receipt storage must not
modify the notebook unless the user explicitly requests an export. A cached
receipt is valid only for the exact document revision, plan, inputs, engine
identity, and effective policy it names.

### 12.5 Signing extension

Implementations may sign receipts. A signed receipt must name its signature
algorithm, key identifier, and signed canonical bytes. Signing is outside core
conformance, and an unsigned receipt must never be presented as authenticated.

## 13. Required error codes

The following codes have stable meanings:

| Code | Meaning |
|---|---|
| `invalid_request` | Request JSON is malformed or violates the command schema. |
| `unsupported_protocol` | Requested protocol version is unavailable. |
| `unsupported_capability` | Requested behavior is not implemented. |
| `document_not_found` | The requested PMD file does not exist. |
| `document_invalid` | PMD static validation failed. |
| `unknown_cell` | A referenced cell ID does not exist. |
| `revision_conflict` | Current document bytes do not match the request revision. |
| `operation_precondition_failed` | An operation-specific digest or state precondition failed. |
| `dependent_cells_exist` | A deletion would leave references to a missing cell. |
| `transaction_invalid` | The complete candidate document is invalid. |
| `response_budget_too_small` | Mandatory response data cannot fit the requested budget. |
| `authorization_required` | Execution was requested without host authorization. |
| `policy_blocked` | Effective policy prohibits required work. |
| `policy_unenforceable` | The runner cannot enforce a required restriction. |
| `limit_exceeded` | A declared execution or response limit was reached. |
| `required_input_changed` | A declared input changed after planning. |
| `document_changed_during_verification` | Notebook bytes changed while verification was running. |
| `cell_failed` | A code/setup cell returned an unsuccessful result. |
| `test_failed` | A test cell returned an unsuccessful result. |
| `internal_error` | The runner failed outside notebook-controlled execution. |

Implementations may add codes but must not redefine these.

## 14. Trust, policy, and secrets

### 14.1 Untrusted content boundary

All content originating in a PMD document or its execution is untrusted,
including:

- Narrative, headings, links, and frontmatter.
- Cell source and comments.
- Standard output and standard error.
- Rich outputs and attachments.
- Cached values and prior receipts.
- Fields labeled as author or agent instructions.

Protocol responses must label returned notebook content with
`"content_trust": "untrusted"`. This label is informational; it does not
sanitize content or prevent prompt injection.

An agent host should keep protocol data separate from system/developer policy
and must not treat notebook prose such as "ignore previous instructions" as
host authorization.

### 14.2 Optional document agent metadata

A PMD document may provide advisory metadata:

```yaml
agent:
  guidance:
    - "Preserve the raw input schema."
    - "Changes to compute should pass test-compute."
  context:
    default_depth: 1
    max_bytes: 65536
  verification:
    tests: impacted
    include_downstream: true
  restrictions:
    network: deny
    environment_allow:
      - SALES_API_TOKEN
```

This metadata is document policy and untrusted content. A runner may use it to
narrow behavior. It must never use it to bypass host authorization or broaden
host policy.

### 14.3 Effective policy

Effective policy is the intersection of:

1. Runner hard limits.
2. Host policy.
3. Document restrictions.
4. Request restrictions.

When policies disagree, the more restrictive rule wins. Absence of a document
restriction does not imply permission.

The verification plan and receipt must report each policy source, the effective
value, and whether it was enforced. A runner unable to enforce a required
restriction must block rather than silently continue.

### 14.4 Secrets

Requests may name environment variables or secret handles but must not require
secret values in notebook source or protocol JSON. A runner must redact secret
values from:

- Commands and environment reports.
- stdout/stderr previews when exact-value redaction is possible.
- Diffs, diagnostics, plans, and receipts.

Because arbitrary code can transform or exfiltrate a secret, redaction is not a
security boundary. The receipt must state which secret names were made
available, never their values.

### 14.5 Filesystem and network claims

Process isolation alone is not filesystem or network isolation. A runner must
advertise whether it can enforce network and filesystem policy. If it cannot,
receipts must state that host filesystem or network state may have influenced
execution.

## 15. End-to-end example

### 15.1 Inspect

```console
pmd agent inspect sales.pmd --request inspect.json
```

The client requests `compute`, one upstream level, downstream dependents, and
tests under a 64 KiB response budget. It receives exact cell IDs, digests,
resolved dependencies, adjacent narrative, and explicit omissions.

### 15.2 Apply

```console
pmd agent apply sales.pmd --request change.json
```

`change.json` names the inspected document revision and expected source digest.
The runner changes only `compute`, validates the complete document, writes it
atomically, and returns:

```json
{
  "change_token": "opaque-runner-token",
  "changed_cells": ["compute"],
  "impact": {
    "affected": ["compute", "report"],
    "impacted_tests": ["test-compute"]
  },
  "recommended_verification": {
    "document_revision": "sha256:new...",
    "change_token": "opaque-runner-token",
    "include_downstream": true,
    "tests": "impacted",
    "fresh": false
  }
}
```

### 15.3 Plan without authority

```console
pmd agent verify sales.pmd --request verify.json
```

No cell runs. The response contains the deterministic plan and exits `5` with
`authorization_required`.

### 15.4 Verify

```console
pmd agent verify sales.pmd --request verify.json --allow-execution
```

Unchanged dependencies may come from valid cache entries. `compute` and
`report` execute, then `test-compute` executes. The receipt identifies the
document, inputs, sources, engines, outputs, policy, cache use, and test result.

An agent can now accurately say:

> I changed `compute`; PMD executed `compute` and downstream `report`, ran
> `test-compute`, and verified the declared plan for document revision
> `sha256:new...`. Host filesystem state remained observable, so undeclared
> external-input influence was not ruled out.

It may not accurately claim that the change is universally correct or fully
hermetic.

## 16. Conformance checklist

### Reader

- [ ] `capabilities` returns deterministic machine-readable features and limits.
- [ ] `inspect` can select a cell by stable ID without returning the whole file.
- [ ] Explicit and resolved dependencies are distinguishable.
- [ ] Requested content is either complete or explicitly omitted with size and digest.
- [ ] Response size respects `max_bytes`.
- [ ] Notebook content is labeled untrusted.
- [ ] Inspection never executes cells.

### Editor

- [ ] Every mutation requires an exact base revision.
- [ ] Stale mutations change no bytes.
- [ ] The minimum operation set in section 9.3 is supported.
- [ ] Failed multi-operation transactions change no bytes.
- [ ] Successful edits preserve unrelated bytes.
- [ ] Candidate documents are parsed and validated before commit.
- [ ] Apply returns a diff, impact result, and recommended verification request.

### Verifier

- [ ] Verification requires an exact document revision.
- [ ] Planning starts no processes without host execution authorization.
- [ ] Changed cells, downstream cells, dependencies, and impacted tests are explicit.
- [ ] Missing tests are distinct from omitted tests.
- [ ] Unenforceable required policy prevents a verified result.
- [ ] Receipts bind results to document, plan, inputs, engines, and outputs.
- [ ] Document or declared-input races prevent a verified result.
- [ ] `verified` is scoped to the stated plan and does not claim semantic proof.

## 17. Open extension points

The following are deliberately outside v0.1:

- JSON Schema documents for request and response validation.
- Typed cell input/output contracts.
- Model Context Protocol tool mappings.
- Receipt signatures and transparency logs.
- Semantic language analysis beyond the PMD dependency graph.
- Multi-document graphs and repository-wide impact analysis.
- Transactional edits spanning multiple files.
- Human approval workflows and policy languages.
- Standardized package/environment locks.
- Remote execution and distributed caches.

Extensions must preserve revision preconditions, explicit omissions, untrusted
content boundaries, and the rule that document content cannot grant authority.

## 18. Versioning

**pmd-agent/0.2 (2026-08-24)** adds rendered inspection, named narrative and
replacement evidence, actionable blocked receipts, declared capabilities,
engine identity, structured failures, and authorized NDJSON execution events.

**pmd-agent/0.1** is the initial draft. A client must discover supported
versions through `capabilities` and reject an unknown `protocol` value.
