# Proposal 0006: UTF-8-safe CLI output

**Status:** Implemented (0.4.0)
**Fixes:** [known-issues.md → BUG-2](../docs/known-issues.md#bug-2-cli---verbose-echo-of-cell-output-still-crashes-outside-cp1252)
**Touches:** `spec.md` §5.4 (process isolation, by analogy), `cli.py`
(`_print_results`, `main`)
**Found while verifying:** [proposals/0001](0001-utf8-safe-cell-source.md),
in 0.3.0

## Motivation

[Proposal 0001](0001-utf8-safe-cell-source.md) fixed cell *source*
transmission and cell *output capture* to be unconditionally UTF-8, and it
shipped correctly in 0.3.0 — verified directly, see
[known-issues.md's BUG-1 entry](../docs/known-issues.md#bug-1-non-ascii-in-a-code-cell-crashes-with-a-misleading-pep-263-error).
That fix works by giving the **cell subprocess** an explicit UTF-8 contract:
byte-mode stdin, explicit UTF-8 decode of captured stdout/stderr, and
`PYTHONUTF8=1` injected into that subprocess's environment.

It does not do anything for the **outer `pmd.exe` process's own stdout**.
Once `runner.py` has correctly decoded a cell's captured output into a
Python `str`, `cli.py`'s `_print_results()` hands that string to a plain
`print(...)`, writing to `pmd.exe`'s *own* `sys.stdout` — and that process
was launched directly by the user's shell, with no UTF-8 override of its
own. On Windows, printing a character outside the host's locale codepage
(cp1252 in the environment where this was found; CJK, emoji, and much of
Cyrillic fall outside it) raises `UnicodeEncodeError` and crashes the CLI
outright, even though the cell it's reporting on already finished
successfully.

Concretely reproduced: a one-line cell printing `中文` and an emoji,
run with `pmd run --fresh --verbose`, crashes `pmd.exe` itself while trying
to *echo* that already-successful cell's output to the console. Confirmed
this does **not** affect `pmd render` (writes its HTML file directly with
`encoding="utf-8"`, never routing through this `print()` call at all) or a
failing cell's own traceback (Python's `stderr` defaults to
`errors="backslashreplace"` for uncaught exceptions, so traceback content
arrives at this code path pre-escaped to ASCII) — this is specifically about
a cell's **explicit**, successful `stdout`/`stderr` writes containing
non-cp1252 content, echoed by `--verbose` or by a failing cell's stderr
dump.

## Proposal

Apply the same category of fix used for the cell subprocess to the `pmd.exe`
process itself, at CLI startup (`main()` in `cli.py`, before any output is
produced):

1. The CLI **MUST** ensure its own `sys.stdout` and `sys.stderr` write UTF-8
   regardless of host locale. Two equivalent implementation paths:
   - **(a)** `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`
     and the same for `sys.stderr`, called once at the top of `main()`. Works
     on any CPython new enough to have `TextIOWrapper.reconfigure` (3.7+, so
     no tension with this project's existing 3.10+ floor).
   - **(b)** Set `PYTHONUTF8=1` in `pmd.exe`'s own environment before Python
     starts — not applicable as an in-process fix (the interpreter has
     already started by the time `main()` runs), but relevant if the
     installed `pmd` entry point can be generated as a wrapper that sets this
     before invoking Python. (a) is the more portable, self-contained fix and
     the one this proposal recommends.
2. `errors="replace"` (not `"strict"`) on the reconfigured streams, so that
   even in some future environment where UTF-8 itself can't be written for
   some reason, the CLI degrades to `?` placeholders instead of crashing —
   consistent with how `runner.py` already treats the analogous decode step
   (`errors="replace"` on the captured-output decode, per proposal 0001).
3. This is purely an output-encoding fix; it does not change any cell
   execution semantics, cache key, or the render/HTML path (already correct,
   per the Motivation section above).

## Conformance addition

Add to spec.md §13 (conformance checklist), alongside proposal 0001's entry:

- [ ] A code cell printing a character outside the host's default locale
      codepage (e.g. CJK or emoji on a Windows cp1252 host) is echoed
      correctly by `pmd run --verbose` instead of crashing the CLI process.

## Alternatives considered

- **Tell users to set `PYTHONUTF8=1` themselves before invoking `pmd`.**
  Rejected as the primary fix for the same reason proposal 0001 rejected the
  equivalent "just stick to ASCII" workaround: it's a real, non-obvious trap
  for anyone building a notebook that legitimately prints non-Latin content
  (a very plausible thing for, e.g., an internationalized project's data),
  and nothing about the crash's `UnicodeEncodeError: 'charmap' codec` message
  hints at the fix. Worth documenting as a workaround until this ships (added
  to `known-issues.md`), not as the permanent answer.
- **Fix only `_print_results`'s specific `print()` calls with an explicit
  `.encode("utf-8", errors="replace").decode("utf-8")` round-trip, instead of
  reconfiguring the streams globally.** Would work for the two call sites
  that exist today, but is a narrower, more fragile fix — any future
  `print()`/`sys.stdout.write()` added anywhere else in `cli.py` (e.g. a
  future `--lint-inputs` or `agent` command echoing document content) would
  reintroduce the same bug. Reconfiguring the stream once at startup fixes
  the whole process, not just the two call sites known about today.

## Open questions

- Should this same reconfiguration also apply to `pmd agent`'s JSON-object
  stdout writes (`_run_agent` in `cli.py`)? Those are already
  `json.dumps(..., ensure_ascii=False)`, which produces literal UTF-8
  characters in the JSON text (not `\uXXXX` escapes) — so they'd hit the
  exact same crash today if a notebook's narrative or cell source contained
  non-cp1252 content and got echoed back through an `agent inspect`
  response. Likely yes, same fix, same startup call — flagged so whoever
  implements this doesn't fix only the `run`/`test`/`render` code paths and
  miss the agent protocol's.
