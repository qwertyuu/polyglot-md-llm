# PMD 0.6 demo

Run these commands from this directory with the project virtual environment
activated.

## 1. Static structure

```console
pmd check notebook.pmd --graph
```

This validates the typed contract and declared network host. The unannotated
JSON fence remains narrative.

## 2. Parameter overrides and sweeps

```console
pmd run notebook.pmd --set tuiles.canada=1600 --fresh --verbose
pmd run notebook.pmd --sweep tuiles.canada=1400,1568,1800 --verbose
```

Each variant has an isolated context and a distinct cache key.

## 3. Notebook as a function

```console
pmd call notebook.pmd --input "@input.json" --output totaux --fresh
```

Successful stdout is only the contracted JSON value.

## 4. Reader views and document tests

```console
pmd render notebook.pmd --to text --fresh --out ../../dist/demo-0.6.txt
pmd render notebook.pmd --to html --hide-graph --hide-source --out ../../dist/demo-0.6-reader.html
pmd test notebook.pmd --fresh --verbose
```

The text and HTML views contain semantic tables and aligned standard output.
The document-level test checks the same reader-visible text.

## 5. Agent views and streaming

```console
pmd agent inspect notebook.pmd --include-rendered --allow-execution
pmd agent inspect notebook.pmd --request inspect.json
pmd agent run notebook.pmd --stream --allow-execution --fresh
```

Rendered inspection is bounded. Streaming execution emits one NDJSON event per
line, including structured cell results and digests. The bounded inspection
request also exposes heading-derived narrative IDs such as
`section:reader-report`.

## 6. Run comparison

Copy the `Run ID` printed by a normal run:

```console
pmd run notebook.pmd --set tuiles.canada=1568
pmd run notebook.pmd --set tuiles.canada=1600 --compare-with RUN_ID
```

The comparison reports the cells and observable fields whose values changed.

## 7. Structured failure

`failure.pmd` intentionally reads a missing context key:

```console
pmd agent run failure.pmd --stream --allow-execution --fresh
```

The failing `cell_finished` event contains `exception_type=KeyError`, line `1`,
the source line, and `resolved_context={"available":42}`. The downstream-safe
native traceback remains in stderr evidence.

## 8. Provenance

`pmd attest` consumes a verified receipt; it does not execute the notebook or
create that receipt itself. In PowerShell, inspect the current revision, build
a caller-scoped verification request, and retain the complete verification
response:

```powershell
$inspection = pmd agent inspect notebook.pmd --request inspect.json |
  ConvertFrom-Json
$request = @{
  document_revision  = $inspection.document.revision
  changed_cells      = @("scenario")
  include_downstream = $true
  tests              = "all"
  fresh              = $true
  render             = $true
} | ConvertTo-Json -Depth 5
$request |
  pmd agent verify notebook.pmd --request - --allow-execution |
  Tee-Object -FilePath receipt.json
```

Only a receipt whose status is `verified` can be attested:

```powershell
(Get-Content receipt.json -Raw | ConvertFrom-Json).result.receipt.status
```

Then emit the attestation:

```console
pmd attest notebook.pmd --receipt receipt.json --out ../../dist/demo-0.6.intoto.json
```

The output is an explicitly unsigned in-toto Statement with a SLSA provenance
predicate, bound to the exact PMD document revision and interpreter identity.
