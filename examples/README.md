# Examples

All commands below run from the repository root. Every executable example uses
only the Python standard library and PMD's built-in engines.

| Example | What it demonstrates | Platform |
| --- | --- | --- |
| [`basic.pmd`](basic.pmd) | dependencies, JSON context, rich Markdown, test cells | all |
| [`artifacts.pmd`](artifacts.pmd) | CSV and Markdown outputs, dependency attachments, manifests | all |
| [`composition.pmd`](composition.pmd) | declared inputs, cache fingerprints, `role=lib`, `uses`, tags | all |
| [`shell-context.pmd`](shell-context.pmd) | `sh` context helpers consumed by Python | POSIX |
| [`powershell-context.pmd`](powershell-context.pmd) | PowerShell context helpers consumed by Python | Windows |
| [`v0.6/`](v0.6/) | SQL, typed outputs, calls, sweeps, document tests, agent verification, attestations | all |

## Portable examples

```console
pmd check examples/basic.pmd --graph
pmd test examples/basic.pmd --fresh --verbose

pmd test examples/artifacts.pmd --fresh --verbose --out-dir pmd-outputs/artifacts

pmd check examples/composition.pmd --strict-inputs --graph
pmd test examples/composition.pmd --fresh --verbose
pmd run examples/composition.pmd --tag report --verbose
```

The artifact example exports collected files beneath `pmd-outputs/artifacts/`.
The composition example declares `data/measurements.csv`, so edits to that file
invalidate affected cache entries.

## Shell interoperability

On Linux or macOS:

```console
pmd test examples/shell-context.pmd --fresh --verbose
```

On Windows:

```console
pmd test examples/powershell-context.pmd --fresh --verbose
```

## Advanced feature tour

[`v0.6/README.md`](v0.6/README.md) is the complete walkthrough for typed output
contracts, `pmd call`, parameter overrides and sweeps, SQL consumers, reader
views, structured agent failures, verification receipts, and provenance
attestations.
