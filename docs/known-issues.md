# PMD Implementation: Known Issues and Field Notes

**Status:** Living document, not part of the spec. Tracks concrete findings from
running `polyglot-pmd` against a real notebook, as opposed to reading the
source.
**Applies to:** `polyglot-pmd` 0.2.0 (original findings), 0.3.0
(re-verification below), 0.4.0 (BUG-2 fix, verified fully effective; GAP-3
precision retune, verified partially effective), and 0.4.1 (GAP-3 root-cause
fix, verified both by targeted reproduction and by a full rerun against the
original reference document — see [CHANGELOG.md](../CHANGELOG.md)).

## Provenance

Every finding below came from a single real build, not a code-reading exercise:
`paddy_handoff.pmd`, a 13-cell notebook (10 `code`, 3 `role=test`) built with
the `pmd-notebooks` Claude Code skill against the `royalur-cheat-detection`
project (a sibling checkout under `general-python-coding/`, not this repo — the
notebook recomputes cheat-detection statistics live from parquet files rather
than restating them from a report). `pmd check --graph`, `pmd run --fresh`,
`pmd test --fresh`, and `pmd render --to html --fresh` were all run to
completion against it on 2026-08-08, on Windows, using an in-project venv
(`{document_dir}/venv/Scripts/python.exe`) as the Python engine.

Each entry cites the exact source location in this checkout so a fix can be
scoped without re-deriving the root cause. All five items below (BUG-1,
GAP-1..4) were **re-verified against 0.3.0 the same day**, on the same
notebook, by actually exercising the shipped fix rather than reading the diff
— see the "Verified in 0.3.0" note at the end of each entry. That
verification pass also surfaced one new, narrower issue (BUG-2) and one
precision caveat on GAP-3's fix. Both were addressed in 0.4.0, and both were
**re-verified the same way** — re-run against the same document, not read
from the diff — with results recorded inline: BUG-2's fix holds up fully;
GAP-3's retune is real progress but its own CHANGELOG entry overstates the
result (claimed 13→1 false positives, actually measured 13→10, including one
new false-positive class the retune itself introduced). See each entry's
"Fixed/Verified in 0.4.0" note.

## Summary

| ID | Severity | Area | One-line | Status |
|---|---|---|---|---|
| [BUG-1](#bug-1-non-ascii-in-a-code-cell-crashes-with-a-misleading-pep-263-error) | High | engine invocation, Windows | Non-ASCII in a code cell crashes with a misleading PEP 263 error | **Fixed in 0.3.0**, verified — [proposals/0001](../proposals/0001-utf8-safe-cell-source.md) |
| [BUG-2](#bug-2-cli---verbose-echo-of-cell-output-still-crashes-outside-cp1252) | Medium | CLI output, Windows | `pmd run/test --verbose` crashes echoing cell stdout containing characters outside the host codepage (e.g. CJK, emoji) | **Fixed in 0.4.0**, verified — [proposals/0006](../proposals/0006-utf8-safe-cli-output.md) |
| [GAP-1](#gap-1-no-cross-cell-code-sharing) | Medium | ergonomics | No cross-cell code sharing forces literal constant duplication | **Fixed in 0.3.0**, verified — [proposals/0002](../proposals/0002-shared-library-cells.md) |
| [GAP-2](#gap-2-render-silently-excludes-test-cells) | Medium | render | `pmd render` silently excludes `role=test` cells; shipped artifact can't prove its own claims | **Fixed in 0.3.0**, verified — [proposals/0003](../proposals/0003-render-with-tests.md) |
| [GAP-3](#gap-3-declared-inputs-is-unchecked) | Medium | caching | Declared `inputs:` is never checked against what a cell actually reads | **Fixed in 0.3.0**; 0.4.0 retune verified partial (13→10, not claimed 13→1); **0.4.1 root-cause fix verified on the real document (10→4)** — remaining 4 are one known, inherent, low-severity class — [proposals/0004](../proposals/0004-declared-input-linting.md) |
| [GAP-4](#gap-4-no-sanctioned-scratch-iteration-loop) | Low | ergonomics | No sanctioned way to iterate against cached upstream context without permanently editing the document | **Fixed in 0.3.0**, verified — [proposals/0005](../proposals/0005-scratch-patch-execution.md) |

---

## BUG-1: Non-ASCII in a code cell crashes with a misleading PEP 263 error

**Severity:** High — silent-until-it-isn't; any non-ASCII character in a
Python cell's source (an em dash, a curly quote, an accented name) reproduces
this every time, on Windows, with no workaround short of avoiding the
character.

**Symptom:**

```
SyntaxError: Non-UTF-8 code starting with '\x97' in file <stdin> on line 101,
but no encoding declared; see https://peps.python.org/pep-0263/ for details
```

This message is actively misleading. PEP 263 is about *declared* source-file
encodings (`# -*- coding: ... -*-`); the actual problem has nothing to do with
what the cell declares — it's how the runner hands the cell's source to the
interpreter's stdin.

**Root cause:**

`runner.py` invokes the language engine with the cell's bound source piped
over stdin in **text mode**, with no encoding pinned:

```python
# runner.py, inside Runner.run()
process = subprocess.run(
    command, input=source, text=True, capture_output=True, cwd=working_directory,
    env=_cell_environment(...), timeout=timeout,
)
```

`text=True` with no `encoding=` makes Python's `subprocess` module encode
`source` using `locale.getpreferredencoding(False)` before writing it to the
child's stdin pipe. On Windows that's the process codepage (`cp1252` in this
environment), not UTF-8. An em dash (U+2014) encodes to the single byte
`0x97` under cp1252. The *child* Python interpreter reading its own stdin
script, however, assumes UTF-8 for undeclared-encoding source per PEP 263,
sees `0x97` as an invalid continuation byte, and raises the error above.

The bug is entirely in the parent-side encode step, not in anything the cell
author wrote. `bindings.py`'s `PYTHON_BINDING` preamble (prepended to every
Python cell — see `source_with_binding()`) is itself pure ASCII, so it isn't
the trigger; any non-ASCII character anywhere in the *user's* cell source is
enough.

**Reproduction:**

```console
$ printf 'print("em dash: \xe2\x80\x94")\n' > /tmp/repro.pmd  # (wrap in a cell first)
```

Or, more directly, run any `.pmd` document containing a Python cell whose
source (including comments and string literals) has an em dash, curly quote,
or any character outside the target codepage, with `pmd run --fresh` on
Windows.

**Impact observed:** a full `--fresh` run of a 13-cell document failed at the
first offending cell and blocked all nine downstream cells (`Blocked by
failed dependency: ...`), even though only the prose in `print()` calls was
at fault — no logic was wrong. Recovery required manually grepping the
document for `[’‘“”–—]` and hand-editing eight lines across three cells.

**Suggested fix:** see [proposals/0001](../proposals/0001-utf8-safe-cell-source.md).

**Workaround (current, pre-0.3.0 only):** keep code-cell source (including
string literals and comments) strictly ASCII. Narrative Markdown between
cells is unaffected — it is never executed, so accented names, em dashes,
and smart quotes are safe there.

**Verified in 0.3.0 (2026-08-08):** restored the em dashes this workaround
had stripped from eight `print()` calls in `paddy_handoff.pmd` and reran
`pmd run --fresh`. All ten cells passed; the rendered HTML (the artifact that
actually matters — it's what ships to a reader) decodes as valid UTF-8 with
every em dash intact (confirmed by decoding the output file and counting
U+2014 occurrences, not by eyeballing a terminal). The fix in
`runner.py` matches [proposals/0001](../proposals/0001-utf8-safe-cell-source.md)
exactly: byte-mode stdin (`input=source.encode("utf-8")`, no `text=True`),
explicit `.decode("utf-8", errors="replace")` on captured stdout/stderr, and
`PYTHONUTF8=1` injected into the cell subprocess's environment. This exact
combination also surfaced [BUG-2](#bug-2-cli---verbose-echo-of-cell-output-still-crashes-outside-cp1252),
a narrower, related issue one layer up the process chain — see below.

---

## BUG-2: CLI `--verbose` echo of cell output still crashes outside cp1252

**Severity:** Medium — narrower than BUG-1 (doesn't affect the common
em-dash/curly-quote/accented-Latin case, since those happen to be
representable in Windows' cp1252, and doesn't affect `pmd render`'s HTML
output at all, since that's written to a file with explicit
`encoding="utf-8"` and never round-trips through this code path). Found
while verifying the BUG-1 fix, not by code reading.

**Symptom:** a cell whose stdout contains a character outside the *parent*
`pmd.exe` process's own locale codepage — CJK, emoji, Cyrillic; anything
past cp1252's repertoire on this Windows machine — crashes `pmd run`/
`pmd test` when `--verbose` is passed (and, for a *failing* cell, even
without `--verbose`, since `_print_results` in `cli.py` always echoes a
failed cell's stderr):

```
UnicodeEncodeError: 'charmap' codec can't encode characters in position 5-6:
character maps to <undefined>
```

**Reproduction:** a one-cell document whose only line is
`print("cjk: 中文  emoji: \U0001F600")`, run with `pmd run file.pmd --fresh
--verbose` on Windows with a cp1252 (or similarly narrow) console codepage.
The cell itself reports `PASSED` — the crash happens strictly in the CLI's
own subsequent echo of that already-successful cell's captured stdout back
to the user's terminal.

**Root cause:** `_cell_environment()` in `runner.py` injects `PYTHONUTF8=1`
into the environment of the spawned **cell** subprocess only. The **outer**
`pmd.exe` process — the one running `cli.py`'s `_print_results()`, which
calls plain `print(cell.stdout, ...)` — was launched by the user's own shell
with no such override, so its `sys.stdout` falls back to the same
locale-preferred codepage that caused BUG-1, one process boundary later.
Because the child cell's stdout was already correctly decoded to a Python
`str` by the time it reaches this `print()` call, the failure mode is subtly
different from BUG-1 (an *encode* error re-serializing a correct string, not
a *decode* error on malformed input) but the underlying cause — a Windows
process without UTF-8 forced that's asked to handle arbitrary Unicode — is
the same class of bug BUG-1 was.

Confirmed **not** to affect: `pmd render` (writes its HTML file directly with
`encoding="utf-8"`, never routes cell output through this `print()`); a
failing cell whose traceback is the source of the non-ASCII content (Python's
`stderr` stream defaults to `errors="backslashreplace"` for uncaught
exceptions regardless of platform, so `中文` in a traceback message arrives
at this `print()` call pre-escaped as `中文` — already ASCII, so it
doesn't trip this bug; this only reproduces via **explicit** `stdout`/`stderr`
writes of raw non-ASCII content, not via an unhandled exception's own
message).

**Suggested fix:** see [proposals/0006](../proposals/0006-utf8-safe-cli-output.md)
— apply the same treatment used for the cell subprocess to `pmd.exe`'s own
process (`PYTHONUTF8=1` / `sys.stdout.reconfigure(...)` at CLI startup).

**Fixed in 0.4.0:** `cli.py`'s `main()` now calls `_ensure_utf8_streams()`
before any output is produced, which reconfigures `sys.stdout`/`sys.stderr`
to `encoding="utf-8", errors="replace"` wherever `.reconfigure()` is
available (guarded with a `getattr`/`callable` check so it degrades silently
rather than raising on a stream that doesn't support it, e.g. under a test
harness's output capture). Placed before the `agent` command dispatch too,
so `pmd agent`'s JSON stdout is covered by the same fix, per the proposal's
open question. Verified directly: wrapped an `io.BytesIO` in a
`TextIOWrapper(encoding="cp1252", errors="strict")`, confirmed it raises
`UnicodeEncodeError` on `中文` unpatched, then confirmed
`_ensure_utf8_streams()` makes the identical write succeed and decode back
correctly as UTF-8 — the same failure mode described above, reproduced and
closed without needing an actual cp1252 console.

---

## GAP-1: No cross-cell code sharing

**Severity:** Medium — doesn't block anything, but actively degrades
maintainability as a notebook grows, and works against the spec's own stated
goal (§5.4: no shared memory across cells) without providing anything in its
place for *code* (as opposed to *data*) reuse.

**Observed:** the bot-identification table (`BOT_SIDE`, a 12-entry dict
mapping game IDs to sides) and the corresponding `BOT_TIGHTNESS` scores were
needed, byte-for-byte identical, in three separate cells (`bot_roster`,
`quantization_baseline`, `move_error_shape`), because §5.4's process isolation
means nothing survives between cells except what round-trips through `ctx`
(JSON-serializable values only — not source code) or the filesystem. `ctx`
is the correct channel for *data* produced by one cell and consumed by
another; it has no equivalent for *code* — a helper function, a constant
table, an import — that several cells want to use identically.

The result: three literal copies of the same 12-line dict in the same
document, with nothing enforcing they stay in sync. A 13th confirmed bot
requires editing all three in lockstep by hand.

**Why this isn't just "write it to `ctx` instead":** `ctx` values must be
JSON-serializable (spec §6.2); a Python dict of strings survives that fine,
but the *moment* two cells need to derive something from it in an
engine-specific way (e.g., "join this against a dataframe"), you're back to
duplicating the surrounding code, not just the data.

**Proposal:** [proposals/0002](../proposals/0002-shared-library-cells.md).

**Verified in 0.3.0 (2026-08-08):** refactored `paddy_handoff.pmd` for real —
pulled the `BOT_SIDE`/`BOT_TIGHTNESS` dicts out of the three cells that
duplicated them into one `role=lib` cell (`#bot_constants`), added
`uses=bot_constants` to each consumer, and deleted the three duplicate
definitions. `pmd check --graph` confirms the `lib` cell is correctly
excluded from the execution graph (shows as an isolated root, no downstream
execution edges) and that implicit sequential `depends-on` chaining still
skips it exactly like it skips `scratch`/`test` cells, so the rest of the
graph was untouched by the insertion. `pmd run --fresh` and `pmd test
--fresh` after the refactor reproduce **byte-identical** output to the
pre-refactor, triple-duplicated version — same correlations, same 12-bot
table, same z-scores — confirming the compile-time composition is
semantically inert, exactly as specified.

---

## GAP-2: `render` silently excludes test cells

**Severity:** Medium — not a spec violation (spec.md §11.2 never requires
test cells in the render target), but a real trap for anyone treating a
rendered `.pmd` document as a "verified" artifact.

**Root cause:** `render_html()` calls `Runner().run(document, fresh=fresh)`
with no `tests=` argument (`render.py`, inside `render_html`):

```python
result = result or Runner().run(document, fresh=fresh)
```

`Runner.run`'s default is `tests: bool = False`, which selects
`roles = {"code", "setup"}` (`runner.py`, inside `Runner.run`):

```python
roles = {"test"} if tests else {"code", "setup"}
roots = [candidate for candidate in document.cells if candidate.role in roles and not candidate.skipped]
```

`role=test` cells are therefore never in `roots`, never enter the execution
closure, and never run during `render`. `render.py`'s `_cell_html()` still
emits a section for them (looked up via `by_id.get(cell.id)`, which returns
`None`), rendered with `status = "not-run"` and no output — the cell's
*source* still appears, collapsed, under "View source," but nothing shows it
passed.

**Observed impact:** a document built specifically so its headline claims are
machine-checked (three `role=test` cells asserting things like "all 12
confirmed bots still show elevated captures-suffered") renders as three grey,
content-free "not-run" blocks. The actual verification only happened in a
separate `pmd test` terminal invocation, whose result never made it into the
shipped HTML — a reader of the rendered document has to take the sender's
word for it that the tests passed, which undermines the reason to make them
executable assertions in the first place.

**Proposal:** [proposals/0003](../proposals/0003-render-with-tests.md).

**Verified in 0.3.0 (2026-08-08):** `pmd render paddy_handoff.pmd --to html
--with-tests --fresh` now executes all three `role=test` cells and the
rendered HTML shows real `status-passed` markup for each — confirmed by
grepping the output file, not by eyeballing the page. Also verified the
failure path deliberately: weakened one test's assertion threshold, re-ran
with `--with-tests`, and got (a) the file still produced, (b) exit code `1`,
(c) the failing cell rendered with `status-failed` and its actual traceback
inline, and (d) a `<div class="warning banner-failed">This render includes
failing tests: test-luck-fairness</div>` at the very top of the document —
exactly the "visually distinguish a failing document" requirement from the
proposal, not just per-cell coloring a reader could scroll past. Reverted the
deliberate breakage afterward; all three tests pass in the shipped notebook.

---

## GAP-3: Declared `inputs:` is unchecked

**Severity:** Medium — a silent-staleness footgun rather than an immediate
failure, which makes it worse in practice (wrong cached results, not a loud
error).

**How it's supposed to work (spec.md §5.5, README "Caching"):** a cell's
cache key includes fingerprints of every path declared under frontmatter
`inputs:` (`runner.py`, `_input_fingerprints` / `Cache.key`). This is the
*only* way an external data file's changes invalidate a cell's cache — the
cache key is otherwise just source text, attributes, engine command, and
upstream `ctx`.

**The gap:** nothing checks that the set of files a cell's source actually
opens is a subset of what's declared. `_declared_inputs()` (`runner.py`)
reads frontmatter `inputs:` and fingerprints exactly those paths — it has no
visibility into what a cell's `pd.read_parquet(...)` calls actually touch.
Forgetting to add a new parquet file to `inputs:` produces no error at
`pmd check` time and no error at `pmd run` time; the cell simply keeps
serving a cache entry keyed on the *old* set of fingerprints even after the
forgotten file changes underneath it.

**Observed impact:** building `paddy_handoff.pmd` required hand-maintaining a
9-entry `inputs:` list in lockstep with which `data/*.parquet` and
`output/*.png` paths got referenced across 10 cells, entirely by inspection —
there was no tool feedback confirming the list was complete, only the
absence of an error.

**Proposal:** [proposals/0004](../proposals/0004-declared-input-linting.md).

**Verified in 0.3.0 (2026-08-08), with a real precision caveat:** two-part
check. **Recall (positive control):** temporarily added an undeclared
`pd.read_parquet("data/player_game_risk.parquet")` call to a copy of
`paddy_handoff.pmd` and confirmed `pmd check --lint-inputs` flagged it
correctly, then removed it — the lint does catch genuine gaps.
**Precision (on the real document):** ran `--lint-inputs` against the actual,
correctly-declared `paddy_handoff.pmd` (9/9 real external files already
covered) and got **13 warnings, all 13 false positives, zero true
positives.** Reading `lint.py`'s implementation (`_looks_like_path` /
`PATH_SEP_RE`) explains all of them, in four distinct categories, none of
which are implementation bugs relative to [proposals/0004](../proposals/0004-declared-input-linting.md)'s
own spec — they're the heuristic behaving exactly as specified, on real
prose, worse than the proposal anticipated:
1. **`display.image(path, name=...)`'s own `name=` argument** — a bare
   output filename like `"17_quantization_tightness.png"` matches the
   extension-suffix rule and gets flagged as an uncovered *input*, even
   though it's a *destination* filename inside `PMD_CELL_OUT`, and the real
   read-path argument right next to it (`"output/17_quantization_....png"`)
   is correctly recognized as covered. 5 of the 13 warnings are this.
2. **Leading escape sequences.** `STRING_LITERAL_RE` extracts raw,
   unescaped source text, so a cell opening with `print("\n...")` — a very
   common spacing idiom — has its literal `\n` (backslash + n as two
   characters, not a real newline) trip `PATH_SEP_RE`'s backslash check
   before Python ever interprets the escape. 3 of the 13 warnings are this.
3. **Numeric fractions in prose.** `"fewer than 8/12 bots..."` and
   `"...9/11/12 stood out"` both contain a real `/`, matching the exact
   heuristic the proposal specified — a plain-English ratio is
   indistinguishable from a Unix path fragment to a regex. 2 of the 13.
4. **Whole-sentence false-positive from a substring match.** The match
   granularity is the *entire string literal* handed to `print(...)`, not a
   path-shaped token within it — so `"Figure from src/analyze_luck_mechanism.py,
   regenerated from this same sample."`, an ordinary citation sentence, gets
   flagged wholesale because it happens to mention a real file path
   mid-prose. 3 of the 13.

**Net assessment:** the mechanism works (real recall, never blocks `pmd
check`'s exit code, per spec), but its signal-to-noise ratio on a
narrative-heavy notebook — exactly PMD's target use case — was 0% on this
document. Worth a follow-up before recommending `--lint-inputs` in CI or by
default; not filed as a new proposal yet since the fix is more a heuristic
retune (extraction should unescape source text; `display.*` calls' `name=`
kwarg should probably be excluded from the scan entirely; matching should
look for a path-shaped *token*, not treat the whole literal as one candidate)
than a new design decision — a natural v2 of
[proposals/0004](../proposals/0004-declared-input-linting.md) rather than a
distinct proposal.

**Retuned in 0.4.0, claimed 13→1, verified 13→10 — CHANGELOG overstates it.**
`lint.py` does implement all three fixes the note above named: `display.*`'s
`name=` kwarg is now excluded from the scan via a dedicated span match;
string literals are unescaped (`\n`/`\t`/`\r`/`\\`/`\'`/`\"`) before the path
heuristic runs; and matching now operates on whitespace-delimited *tokens*
within a literal, stripped of surrounding punctuation, requiring at least one
letter to qualify. Re-ran `pmd check --lint-inputs` against the current
`paddy_handoff.pmd` (0.4.0 CLI, same document, plus the GAP-1 `lib`-cell
refactor from the 0.3.0 pass above — the four `src/....py` citations and the
`len(games)//2` cell were present in both versions of the document, so the
comparison holds) and got **10 warnings**, not 1:

- **Categories 1 and 2 are genuinely, fully fixed** — zero `display.*`
  `name=` false positives, zero leading-escape false positives. Confirmed by
  direct count, not by re-reading the diff.
- **Category 3 (numeric fractions) is only *partially* fixed.** The
  letter-requirement guard does kill a fully bare, isolated fraction like the
  literal `"8/12"` inside `"fewer than 8/12 bots..."` (verified: this specific
  literal no longer appears in the output) — but it does **not** catch the
  much more common shape in this document, an f-string value immediately
  followed by a `/N` suffix with no intervening space, e.g.
  `f"{n_flagged_by_10}/12 flagged"`. `_path_tokens`'s `TOKEN_STRIP_CHARS`
  strips the *delimiting* `{`/`}` characters from a token's ends, but leaves
  the *variable-name text itself* attached to the token if it borders the
  slash with no whitespace — so `{n_captured_positive}/12` becomes the token
  `n_captured_positive}/12` (the trailing `}` survives because stripping
  found the `2` first from the other end and stopped), which contains a
  letter (from the variable name) and a `/`, and passes every guard. Five
  of the 12 tokens in `paddy_handoff.pmd` have exactly this shape
  (`n_captured_positive}/12`, `n_outside_range}/12`, `n_flagged_by_10}/12`
  ×2, `len(bot_shape)}/12`) and all five are still flagged.
- **Category 4 (whole-sentence match) is real progress, not a full fix** —
  as the original note anticipated, the warning now correctly names just
  `src/analyze_luck_mechanism.py` instead of quoting the entire citation
  sentence, but a prose citation of a sibling script is still a false
  positive by the "does this cell *read* this path" test; there are four
  now (one more print statement citing two scripts in one sentence than the
  0.3.0-era document had, both now correctly split into separate token
  warnings instead of one sentence warning).
- **One new false-positive class, not present in 0.3.0:** `len(games)//2`
  inside an f-string (`f"...{len(games)//2:,} games..."`) is now flagged,
  and wasn't before. Root cause is an ordering bug, not a missing
  heuristic: the *old* whole-literal guard (`"{" in literal`) happened to
  correctly suppress this case, because the entire f-string body still
  contained an unstripped `{` at whole-literal granularity. The *new*
  token-level guard checks for `{` too, but only *after*
  `TOKEN_STRIP_CHARS` has already stripped the boundary `{`/`}` off the
  token — so the very check meant to exclude f-string expressions can no
  longer see the brace that would trigger it, and Python's `//`
  floor-division operator reads as a path separator once unmasked.

**Positive control still holds:** re-added the undeclared
`data/player_game_risk.parquet` read used in the 0.3.0 verification and
confirmed `--lint-inputs` still catches it correctly. The "declared input
never referenced" half of the lint also remains clean (no false positives
there in either version). Net assessment: 0.4.0 is a real, substantial
improvement (8 of the original 13 false positives are gone outright) but the
CHANGELOG's "13 to 1" is inaccurate for this document — it's 13 to 10, with
one new false-positive class introduced by the retune itself alongside the
genuine fixes. Still not recommending `--lint-inputs` unattended in CI on a
narrative-heavy document without a per-project `ignore_patterns` tune.

**Fixed in 0.4.1 (2026-08-08):** both the category-3 miss and the new
category-5 regression traced to the *same* single bug, exactly as the
0.4.0 verification note's root-cause analysis identified: `TOKEN_STRIP_CHARS`
(`lint.py`) included `{` and `}` in the set of characters stripped from a
token's ends before `_looks_like_path`'s `"{" in token` unresolved-
interpolation guard ever runs — so the guard's own signal was being removed
by the code meant to feed it. Fix was a one-line change: drop `{`/`}` from
`TOKEN_STRIP_CHARS`, so a token like `{n_flagged_by_10}/12` or
`{len(games)//2}` keeps its brace, correctly trips the existing `"{" in
token` check, and is excluded — no new guard needed, the retune's own
category-1/2 fixes and the letter-requirement guard are untouched.

**Real-document count now confirmed: 10 → 4.** The targeted-reproduction
verification above was written from a session without access to the
`royalur-cheat-detection` checkout; that gap is closed. Reran
`pmd check --lint-inputs paddy_handoff.pmd` (0.4.1 CLI, same document) and
got exactly the four `src/....py`-citation-in-prose warnings
(`luck_mechanism_chart`, `quantization_charts` ×2, `move_error_chart`) and
**nothing else** — all five `{value}/12`-shaped fraction warnings and the
`len(games)//2` floor-division regression are gone, matching the targeted
reproductions exactly and confirming the fix generalizes to the real
document, not just the two minimal cases it was built against. Re-ran the
undeclared-`data/player_game_risk.parquet` positive control directly against
this checkout too: still caught correctly. `pytest` against
`pmd-impl/tests/` (now 51 cases, two more than 0.4.0's 48, from the new
`test_proposals.py` regression cases this fix added): 50 passed, the same
one pre-existing, unrelated cross-drive-letter failure
(`test_document_relative_engine_command`), no regressions.

**Final tally across three releases, one document, measured every time:**
13 (0.3.0) → 13 (0.4.0 CHANGELOG claimed 1) → 10 (0.4.0 measured) → 4
(0.4.1 measured). The remaining 4 are a single, well-understood, lower-severity
class (a purely textual heuristic cannot distinguish "this cell reads that
path" from "this print statement mentions that path in a citation sentence"
without deeper intent-tracking than a regex scan can offer) — not filed as a
new issue, since [proposals/0004](../proposals/0004-declared-input-linting.md)'s
own "Open questions" already named exactly this limitation as expected,
inherent, textual-heuristic behavior rather than a bug to fix.

---

## GAP-4: No sanctioned scratch-iteration loop

**Severity:** Low — a workflow gap, not a defect. Documented because it
measurably shaped how the notebook got built.

**Observed:** before writing a single permanent cell, roughly a dozen ad hoc
`python -c "..."` invocations were run directly in a shell, outside PMD
entirely, to check parquet column names, sanity-check a correlation, and time
a bootstrap loop before committing to a sample size. Only pre-validated logic
was ever typed into an actual `.pmd` cell. `role=scratch` exists (spec.md
§4.6) but only to mark a cell as *permanently excluded* from `run`/`test`/
`render` — it is not a channel for "try this snippet against cell X's
already-resolved upstream context, without writing it into the document."

This is arguably correct behavior for the *document* (nothing half-baked ever
lands in the source), but it means the fast, iterative part of development
happens with no relationship to PMD's process-isolation, caching, or context
model at all — and then has to be manually transcribed back in.

**Proposal:** [proposals/0005](../proposals/0005-scratch-patch-execution.md).

**Verified in 0.3.0 (2026-08-08):** ran `pmd run paddy_handoff.pmd --cell
bot_roster --patch -` twice with different probe snippets piped over stdin.
Confirmed, concretely: (1) the patch correctly sees `BOT_SIDE` from
`bot_constants`, the `uses=`-composed `lib` cell from the GAP-1 verification
above — proposal 0002 and proposal 0005 compose correctly together; (2) the
patch correctly sees upstream `ctx` values (`odds_ratios`,
`corr_acc_rating`) produced by `accuracy_and_win_drivers`, `bot_roster`'s
actual upstream dependency; (3) the patch does **not** see `pf`, a plain
local variable `bot_roster`'s own (unpatched) body would have defined — the
right behavior, since the patch replaces that body rather than appending to
it, and only genuine upstream `ctx` should be visible; (4) a `ctx.set(...)`
call inside the patch did not persist — a subsequent normal (non-patch) run
of the same cell shows the original, correct 12-bot table with no trace of
the probe. Zero document mutation throughout (never called `Edit` on the
`.pmd` file during this check — the patch ran entirely off a piped string).

---

## What worked without friction

Worth recording alongside the complaints, since a field report that only
lists problems is as misleading as one that only lists praise:

- **Process isolation caught a real error, not just a hypothetical one.**
  Recomputing a cell live (rather than restating a prior report's numbers)
  surfaced that one of twelve confirmed-bot timing scores had moved from
  "outside the human range" to "inside it" once the human baseline sample
  grew from 1,077 to 5,450 rows — a genuine finding, not a bug, that a
  copy-pasted-numbers document would have gotten quietly wrong.
- **`pmd check --graph`** caught the dependency structure being exactly what
  the implicit-chaining rule (spec.md §5.2) predicted, with zero explicit
  `depends-on` attributes needed across 13 cells.
- **`display.image`/`display.csv` plus the `PMD_CELL_OUT` convention**
  (spec.md §7.2) meant embedding pre-existing PNG artifacts and a computed
  CSV table into the final HTML took one line each, no client library
  ceremony.
- **`pmd test`'s pass/fail-per-cell report** gave a clean, uniform surface to
  re-verify three separate quantitative claims after editing, with no
  bespoke test runner needed.
- **The 0.3.0 turnaround.** All five proposals below (BUG-1, GAP-1..4) shipped
  in one release, each traceable to a specific proposal doc, each independently
  verifiable — and re-running the exact same real notebook against 0.3.0
  turned up all of the verification detail recorded inline above (BUG-1
  genuinely fixed; GAP-1/2/4 genuinely fixed with no behavior change beyond
  the fix itself; GAP-3 shipped but caught its own precision problem on
  contact with real prose) in under an hour, with no synthetic test cases —
  the existing real document was sufficient to validate or complicate every
  claim. `pytest` against the implementation's own `tests/` (48 cases,
  including a new `test_proposals.py`) passed 47/48; the one failure
  (`test_document_relative_engine_command`) is a pre-existing, unrelated
  cross-drive-letter `os.path.relpath` limitation on Windows, not a
  regression from this release.
- **The 0.4.0 turnaround, and why re-running beats re-reading.** BUG-2
  shipped and was independently reproduced as fixed (byte-level UTF-8 check,
  not a terminal glance) in minutes. GAP-3's retune shipped with a specific,
  falsifiable CHANGELOG claim ("13 to 1") — re-running the exact same lint
  command against the exact same document, rather than trusting the diff or
  the changelog prose, found the real number was 10, with one of the ten
  being a false-positive class the retune itself introduced (the token-level
  brace-stripping unmasking `//` floor-division). Neither of these facts
  would have surfaced from reading the source changes in isolation — the
  floor-division regression in particular only exists as an interaction
  between the *new* stripping order and a guard that worked *by accident* in
  the old whole-literal version; there's no diff hunk that makes that
  interaction obvious. `pytest` stayed green throughout (48/49, one new test
  added, the same pre-existing unrelated failure) — passing tests and an
  accurate real-world number are different questions, and this is a
  concrete case where they disagreed.
