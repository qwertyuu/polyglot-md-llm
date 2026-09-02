from __future__ import annotations

import re
from pathlib import Path

from .models import Document
from .runner import _declared_inputs

DEFAULT_EXTENSIONS = {".parquet", ".csv", ".json", ".db", ".duckdb", ".png", ".jpg", ".jpeg", ".txt"}
DEFAULT_IGNORE_PATTERNS = [r"https?://", r"^/tmp/"]
STRING_LITERAL_RE = re.compile(r"""(['"])((?:(?!\1)[^\\\n]|\\.)*)\1""")
NAME_KWARG_RE = re.compile(r"""name\s*=\s*(['"])((?:(?!\1)[^\\\n]|\\.)*)\1""")
PATH_SEP_RE = re.compile(r"[\\/]")
TOKEN_RE = re.compile(r"\S+")
# Deliberately excludes '{' and '}': stripping them before the unresolved-
# f-string-interpolation check in _looks_like_path would remove the exact
# signal that check looks for (e.g. a `{n}/12` or `{len(games)//2}` token
# would lose its brace and read as a real path fragment).
TOKEN_STRIP_CHARS = "(['\",.;:)]"
LETTER_RE = re.compile(r"[A-Za-z]")
LINT_ROLES = {"code", "setup", "test"}

# Escapes actually observed to cause false positives on real prose (a leading
# `\n`/`\t` spacing idiom, an escaped quote or backslash) - deliberately not
# the full Python escape set, so a genuine single-backslash Windows path
# fragment (e.g. `data\foo.csv`) still trips the path-separator heuristic
# instead of being silently unescaped away.
_ESCAPE_MAP = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"'}
_ESCAPE_RE = re.compile(r"\\(.)")


def _unescape(text: str) -> str:
    return _ESCAPE_RE.sub(lambda match: _ESCAPE_MAP.get(match.group(1), match.group(0)), text)


def _lint_config(document: Document) -> tuple[set[str], list[re.Pattern[str]]]:
    lint = document.frontmatter.get("lint", {})
    if not isinstance(lint, dict):
        lint = {}
    extensions = lint.get("input_extensions", sorted(DEFAULT_EXTENSIONS))
    patterns = lint.get("ignore_patterns", DEFAULT_IGNORE_PATTERNS)
    if not isinstance(extensions, list) or not all(isinstance(item, str) for item in extensions):
        extensions = sorted(DEFAULT_EXTENSIONS)
    if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
        patterns = DEFAULT_IGNORE_PATTERNS
    return {item.lower() for item in extensions}, [re.compile(pattern) for pattern in patterns]


def _looks_like_path(token: str, extensions: set[str], ignore: list[re.Pattern[str]]) -> bool:
    if not token or "{" in token or "\n" in token:
        return False
    if not LETTER_RE.search(token):
        return False
    if any(pattern.search(token) for pattern in ignore):
        return False
    if PATH_SEP_RE.search(token):
        return True
    return Path(token).suffix.lower() in extensions


def _path_tokens(literal: str) -> list[str]:
    unescaped = _unescape(literal)
    tokens = []
    for match in TOKEN_RE.finditer(unescaped):
        token = match.group(0).strip(TOKEN_STRIP_CHARS)
        if token:
            tokens.append(token)
    return tokens


def _excluded_spans(source: str) -> list[tuple[int, int]]:
    """Spans of string literals used as a `name=` kwarg value - the
    `display.*` destination-filename convention (bindings.py), not an input
    path, so excluded from the input-literal scan entirely."""
    return [(match.start(2), match.end(2)) for match in NAME_KWARG_RE.finditer(source)]


def _candidate_literals(source: str) -> list[str]:
    excluded = _excluded_spans(source)
    literals = []
    for match in STRING_LITERAL_RE.finditer(source):
        span = (match.start(2), match.end(2))
        if any(span == excluded_span for excluded_span in excluded):
            continue
        literals.append(match.group(2))
    return literals


def _resolve(token: str, document_dir: Path) -> Path:
    candidate = Path(token)
    return candidate.resolve() if candidate.is_absolute() else (document_dir / candidate).resolve()


def lint_inputs(document: Document) -> list[str]:
    """Best-effort static scan for cell source literals that look like data-file
    paths but aren't covered by declared frontmatter `inputs:`, and declared
    `inputs:` entries no cell source appears to reference. Warnings only —
    never affects `pmd check`'s exit code (see proposals/0004, retuned for
    precision per known-issues.md GAP-3)."""
    extensions, ignore = _lint_config(document)
    document_dir = document.path.resolve().parent if document.path else Path.cwd()
    try:
        declared = _declared_inputs(document)
    except OSError as error:
        return [f"lint-inputs: cannot resolve declared inputs: {error}"]

    warnings: list[str] = []
    referenced: list[Path] = []
    for cell in document.cells:
        if cell.role not in LINT_ROLES:
            continue
        for literal in _candidate_literals(cell.source):
            for token in _path_tokens(literal):
                if not _looks_like_path(token, extensions, ignore) or "PMD_CELL_OUT" in token or token.startswith("src/"):
                    continue
                resolved = _resolve(token, document_dir)
                referenced.append(resolved)
                covered = any(resolved == entry or entry in resolved.parents for entry in declared)
                if not covered:
                    warnings.append(f"{cell.id}: literal path '{token}' is not covered by frontmatter inputs:")

    for entry in declared:
        covered = entry in referenced or any(entry in ref.parents for ref in referenced)
        if not covered:
            warnings.append(f"declared input '{entry}' does not appear to be referenced by any cell source")

    return warnings


def strict_input_findings(document: Document) -> tuple[list[str], list[str]]:
    """Split reliable literal-read findings from advisory stale declarations."""
    findings = lint_inputs(document)
    high = [item for item in findings if "is not covered by" in item]
    low = [item for item in findings if item not in high]
    return high, low
