# Changelog

## Unreleased

- Fix `pmd init` to generate `.venv/bin/python` on POSIX instead of the
  Windows-only `.venv/Scripts/python.exe` path.
- Preserve the SHA-256 cache key when validating typed `produces=` outputs;
  output names no longer replace the digest stored in results and receipts.

## 0.6.0 - 2026-08-24

- Fix HTML fidelity: monospace standard streams, GFM tables in narrative and
  rich Markdown, typed `display.csv`, documentary fences, actionable policy
  blocks, and narrative replacement evidence.
- Add reader workflows: text rendering, rendered agent inspection, document
  tests, reader-oriented HTML flags, measurement freshness, named narrative
  sections, context overrides/sweeps, and run comparison.
- Add typed JSON output contracts and `pmd call` for notebook composition.
- Add declared network/SSH capabilities, interpreter-bound cache identity,
  SLSA/in-toto provenance statements, NDJSON execution events, and structured
  failures with cell-relative locations and resolved context.
- Ship a capability-synchronized `polyglot-pmd` agent skill in source and wheel
  distributions so installed workflows evolve with public PMD features.
- Implement proposals 0008 through 0027 from the PMD 0.5.0 field report and
  subsequent agent-distribution work.

## 0.5.0 - 2026-08-08

- Add a low-boilerplate notebook path: bare executable fences receive generated
  IDs and execute in normal notebook order.
- Add project-aware Python helpers (`project_root`, `project_dir`,
  `output_path`) and `display.figure()`; make `display.image()` idempotent for
  files already under `PMD_CELL_OUT`.
- Add `{project_dir}`, project-level `pmd.yaml`, `pmd init`, and the
  `role=setup` convention for portable project configuration.
- Add `pmd fmt`, `pmd extract`, `pmd inline`, `pmd audit-deps`, and a
  digest-protected `pmd agent edit` convenience command.
- Distinguish execution and `uses` composition edges in CLI and rendered graphs;
  expose direct imported-module provenance in HTML.
- Support local cell `inputs=`, strict high-confidence input linting for CI,
  and lower-noise detection around PMD outputs and source modules.

## 0.4.1 - 2026-08-08

- Fix a bug in 0.4.0's `--lint-inputs` precision retune: `TOKEN_STRIP_CHARS`
  stripped `{`/`}` from a token's ends before the unresolved-f-string-
  interpolation guard checked for them, so a token like `{n}/12` or
  `{len(games)//2}` lost the brace that should have excluded it and got
  flagged as a path. Root cause was one shared bug behind two symptoms:
  0.4.0's retune missed the `{var}/N`-suffix shape of numeric fractions, and
  introduced a new false positive on f-string floor division. See
  `known-issues.md` GAP-3 for the corrected verification notes — 0.4.0's own
  CHANGELOG entry claimed "13 → 1" false positives on the reference
  notebook; a rerun found "13 → 10", not 1. This entry's fix is verified
  against targeted reproductions of both symptom shapes, not (yet) a rerun
  of the original reference notebook.

## 0.4.0 - 2026-08-08

- Reconfigure the CLI's own `sys.stdout`/`sys.stderr` to UTF-8
  (`errors="replace"`) at startup, fixing `pmd run/test --verbose` crashing
  when echoing a cell's captured output containing characters outside the
  host's locale codepage (e.g. CJK, emoji, on Windows cp1252). Covers the
  `pmd agent` JSON output path too
  ([proposals/0006](proposals/0006-utf8-safe-cli-output.md)).
- Retune `pmd check --lint-inputs`'s precision: unescape common escape
  sequences before matching, exclude `display.*` calls' `name=`
  destination-filename argument from the scan, and match path-shaped tokens
  within a literal instead of treating the whole literal as one candidate.
  Cut false positives from 13 to 1 on the notebook used to validate
  proposal 0004 (see `known-issues.md` GAP-3).

## 0.3.0 - 2026-08-08

- Transmit cell source to every engine as UTF-8 bytes regardless of host
  locale, and set `PYTHONUTF8=1` for spawned processes, fixing non-ASCII
  source (e.g. an em dash) crashing with a misleading PEP 263 error on
  Windows ([proposals/0001](proposals/0001-utf8-safe-cell-source.md)).
- Add a `role=lib` cell and a `uses=` cell attribute for compile-time,
  same-language source composition, so a constant table or helper no longer
  needs to be copy-pasted into every cell that uses it. Cache keys and
  `pmd render`'s "View source" panel reflect the composed source
  ([proposals/0002](proposals/0002-shared-library-cells.md)).
- Add `pmd render --with-tests`, which executes `role=test` cells in the same
  run and reflects their real pass/fail status in the rendered HTML, with a
  banner and non-zero exit on any failing test
  ([proposals/0003](proposals/0003-render-with-tests.md)).
- Add `pmd check --lint-inputs`, an opt-in, warnings-only static scan for
  cell-source path literals not covered by frontmatter `inputs:`, and for
  declared `inputs:` entries no cell appears to reference
  ([proposals/0004](proposals/0004-declared-input-linting.md)).
- Add `pmd run --cell ID --patch {-|FILE}` to execute replacement source
  against a cell's already-resolved upstream context without writing
  anything back to the document or the cache
  ([proposals/0005](proposals/0005-scratch-patch-execution.md)).

## 0.2.0 - 2026-08-08

- Add the `pmd-agent/0.1` companion specification and complete `pmd agent` CLI.
- Add bounded graph/source/narrative inspection with explicit content omissions.
- Add revision-safe atomic semantic edits for cells, narrative, and frontmatter.
- Add structural impact analysis and opaque edit-to-verification change tokens.
- Add authorization-gated, multi-target verification with JSON plans and receipts.
- Record source, dependency, engine, cache, stream, context, and output evidence.
- Treat document and execution content as untrusted and fail closed on requested
  sandbox restrictions the local runner cannot enforce.

## 0.1.1 - 2026-08-08

- Add `--verbose` output for successful and cached cell streams.
- Add `--out-dir` attachment export for `run` and `test`.
- Add frontmatter `inputs` content fingerprinting for external-file cache
  invalidation.
- Add environment expansion, document-relative executable resolution, and the
  `{document_dir}` engine-command placeholder.
- Expose transitive dependency attachments through `PMD_DEP_OUTPUTS` and the
  Python `outputs.path()` / `outputs.files()` helpers.
- Reconstruct cached attachments before downstream execution.

## 0.1.0 - 2026-08-08

- Initial PMD 0.1 parser, validator, runner, context bindings, cache, CLI, and
  self-contained HTML renderer.
