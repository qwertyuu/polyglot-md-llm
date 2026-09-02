from __future__ import annotations

import re
from pathlib import Path

import yaml

from .parser import load


def format_document(path: str | Path) -> str:
    """Normalize PMD metadata and fence attributes without changing source bodies."""
    document = load(path)
    frontmatter = dict(document.frontmatter)
    front = ""
    if document.body_start:
        front = "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).rstrip() + "\n---\n\n"
    body = document.source[document.body_start:]
    for cell in reversed(document.cells):
        attrs = [f"#{cell.id}"] + [f"{key}={cell.attrs[key]}" for key in sorted(cell.attrs)]
        opening = f"```{cell.language} {{" + " ".join(attrs) + "}"
        old_opening_end = body.rfind("\n", 0, cell.start - document.body_start) + 1
        old_opening_stop = body.find("\n", old_opening_end)
        if old_opening_stop < 0:
            old_opening_stop = old_opening_end + len(body[old_opening_end:])
        body = body[:old_opening_end] + opening + body[old_opening_stop:]
    return (front + body.rstrip() + "\n")


def extract_cell(notebook: str | Path, cell_id: str, destination: str | Path | None = None) -> Path:
    document = load(notebook)
    cell = document.lookup.get(cell_id)
    if cell is None:
        raise ValueError(f"unknown cell: {cell_id}")
    target = Path(destination) if destination else Path(notebook).with_name(f"{cell_id}.{cell.language}")
    target.write_text(cell.source + "\n", encoding="utf-8")
    return target


def inline_file(notebook: str | Path, source: str | Path, cell_id: str | None = None) -> str:
    module = Path(source)
    language = {".py": "python", ".sh": "bash", ".sql": "sql", ".ps1": "powershell"}.get(module.suffix.lower(), module.suffix.lstrip("."))
    identity = cell_id or re.sub(r"[^a-z0-9_-]", "-", module.stem.lower()).strip("-") or "cell"
    return f"```{language} {{#{identity}}}\n{module.read_text(encoding='utf-8').rstrip()}\n```\n"


def audit_dependencies(document_path: str | Path) -> list[str]:
    document = load(document_path)
    root = Path(document_path).resolve().parent
    paths: set[str] = set()
    for cell in document.cells:
        for match in re.finditer(r"(?:from|import)\s+([A-Za-z_][\w.]*)", cell.source):
            candidate = root / (match.group(1).replace(".", "/") + ".py")
            if candidate.exists():
                paths.add(candidate.relative_to(root).as_posix())
    return sorted(paths)
