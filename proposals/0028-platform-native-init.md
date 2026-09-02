# Proposal 0028: Platform-native `pmd init` interpreter path

**Status:** Implemented (0.6.1)
**Fixes:** `pmd init` writes a Windows interpreter path on POSIX
**Touches:** project initialization and portable-engine documentation

## Motivation

On macOS and Linux, `pmd init` writes
`{project_dir}/.venv/Scripts/python.exe`. The generated notebook therefore
fails immediately with a missing executable, but the failure appears at cell
execution time and does not identify the initializer as its cause.

## Proposal

1. `pmd init` **MUST** write `.venv/Scripts/python.exe` on native Windows.
2. `pmd init` **MUST** write `.venv/bin/python` on macOS, Linux, and other
   POSIX platforms.
3. Tests **MUST** cover both template variants independently of the host that
   runs the suite.
4. PMD continues to select an existing environment; initialization does not
   create a virtual environment or install dependencies.

## Alternatives considered

- **Use `python` from `PATH`.** This is portable but makes project execution
  depend on the invoking shell rather than the project's declared environment.
- **Generate both paths and fall back at runtime.** Engine commands are
  intentionally explicit; hidden fallback would weaken reproducibility.
