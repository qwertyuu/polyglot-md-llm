# Proposal 0001: UTF-8-safe cell source transmission

**Status:** Implemented (0.3.0)
**Fixes:** [known-issues.md → BUG-1](../docs/known-issues.md#bug-1-non-ascii-in-a-code-cell-crashes-with-a-misleading-pep-263-error)
**Touches:** `spec.md` §5.4 (process isolation), `runner.py` (`Runner.run`)

## Motivation

Every language engine receives its cell's source over a text-mode stdin pipe
with no encoding pinned. `subprocess.run(..., input=source, text=True)`
encodes `source` using the platform's locale-preferred encoding before
writing it — `cp1252` on the Windows machine this was found on, not UTF-8.
Any non-ASCII character in a code cell (an em dash, a curly quote, an
accented name in a comment or string literal) is silently mis-encoded in
transit, and the *child* interpreter — which assumes UTF-8 for source with no
declared encoding, per PEP 263 for Python — then fails with an error that
names the wrong layer of the problem:

```
SyntaxError: Non-UTF-8 code starting with '\x97' in file <stdin> on line 101,
but no encoding declared; see https://peps.python.org/pep-0263/ for details
```

This is not a Python-specific problem in principle (any engine reading a
byte-oriented script from stdin makes the same encoding assumption a modern
default toolchain does, which is UTF-8), but it currently only manifests
concretely with the Python engine because that's the one whose error message
happens to explain itself. A bash or PowerShell cell with the same underlying
transmission bug would fail with a *less* diagnosable error — likely garbled
output rather than a clean exception.

The spec (§5.4) requires process isolation but says nothing about the
encoding contract for handing a cell's source to its process. This proposal
fills that gap.

## Proposal

1. The runner **MUST** transmit cell source to every engine as UTF-8 bytes,
   unambiguously, regardless of host locale. Two implementation strategies
   satisfy this; an implementation may pick either, or vary by platform:

   - **(a) Explicit encoding on the pipe.** Replace
     `subprocess.run(command, input=source, text=True, ...)` with byte-mode
     input: `subprocess.run(command, input=source.encode("utf-8"),
     text=False, ...)`, and decode `stdout`/`stderr` explicitly as UTF-8
     (`errors="replace"` to avoid a second failure mode on a misbehaving
     engine's own output).
   - **(b) Temp-file transmission.** Write the bound cell source to a
     temporary file with explicit `encoding="utf-8"`, and invoke the engine
     with that file as an argument instead of piping over stdin (e.g.
     `python /tmp/pmd-cell-<id>.py` instead of `python < source`). This
     sidesteps pipe-encoding entirely and has the side benefit of giving
     tracebacks a real filename instead of `<stdin>`.

   (b) is the stronger fix — it also improves error messages (a traceback
   pointing at `<stdin>` line 101 is harder to act on than one pointing at a
   real path) — but (a) is a smaller diff. Either satisfies this proposal;
   an implementation **MUST NOT** ship a fix that only addresses the Python
   engine and leaves bash/PowerShell/SQL on the old locale-dependent path.

2. For engines where forcing UTF-8 requires an environment variable rather
   than an encoding argument (CPython in particular honors
   `PYTHONIOENCODING` and `PYTHONUTF8`), the runner **SHOULD** also set
   `PYTHONUTF8=1` in the spawned process's environment (`_cell_environment`
   in `runner.py` already builds a per-cell environment dict — this is an
   additive key, not a new mechanism) as defense in depth, independent of
   which transmission strategy is chosen.

3. This does not change the cross-language `ctx` contract (spec §6), which is
   already JSON-based and therefore already UTF-8-safe by construction
   (`json.dumps(..., ensure_ascii=False)` is used in `bindings.py`'s
   generated Python binding); only the *source transmission* path is in
   scope.

## Conformance addition

Add to spec.md §13 (conformance checklist):

- [ ] A code cell containing a non-ASCII character (e.g. an em dash) in a
      comment or string literal executes identically on Windows and POSIX.

## Alternatives considered

- **Document it as a known limitation and tell authors to stick to ASCII.**
  Rejected as the primary fix — it's a real, easy-to-hit trap for anyone
  writing prose-heavy `print()` output (exactly the kind of thing a
  narrative-heavy PMD document full of `print()`-based reporting encourages),
  and the error message gives no hint that ASCII-only is the rule. Worth
  keeping as a documented workaround (already added to
  `known-issues.md`) until the fix ships, not as the permanent answer.
- **Fix only the Python engine's binding.** Rejected — the encoding problem
  is in the parent-side pipe write, before any per-language binding code
  runs; a per-engine binding fix wouldn't touch the actual bug.

## Open questions

- Should the runner detect and reject non-UTF-8-representable source at
  `pmd check` time (impossible in practice — all Python `str` source is
  already representable in UTF-8 by definition; this only matters if a
  future engine's bound source could contain raw bytes) — likely not
  applicable, flagged for completeness.
