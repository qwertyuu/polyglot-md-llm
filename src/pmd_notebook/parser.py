from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

import yaml

from .models import Cell, Document

ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
OPEN_FENCE_RE = re.compile(r"^(?P<fence>`{3,})(?P<info>[^`]*)$")
ATTR_BLOCK_RE = re.compile(r"^(?P<lang>[\w+-]+)\s*(?P<attrs>\{.*\})?\s*$")
KNOWN_ATTRIBUTES = {
    "role", "depends-on", "independent", "test-of", "timeout", "env",
    "expect-exit-code", "skip", "tags", "uses", "inputs", "stale-after", "produces",
}
DOCUMENTARY_LANGUAGES = {"console", "diff", "json", "log", "text", "toml", "yaml", "yml"}
STALE_AFTER_RE = re.compile(r"^[1-9]\d*(?:\.\d+)?[smhd]$")


def _frontmatter(text: str) -> tuple[dict[str, Any], int, list[str]]:
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}, 0, []
    lines = text.splitlines(keepends=True)
    offset = len(lines[0])
    for line in lines[1:]:
        if line.rstrip("\r\n") == "---":
            end = offset + len(line)
            try:
                value = yaml.safe_load(text[len(lines[0]):offset]) or {}
                if not isinstance(value, dict):
                    return {}, end, ["frontmatter must be a YAML mapping"]
                return value, end, []
            except yaml.YAMLError as error:
                return {}, end, [f"invalid YAML frontmatter: {error}"]
        offset += len(line)
    return {}, 0, ["unterminated YAML frontmatter"]


def _attributes(raw: str) -> tuple[str | None, dict[str, str], list[str]]:
    errors: list[str] = []
    try:
        tokens = shlex.split(raw[1:-1], posix=True)
    except ValueError as error:
        return None, {}, [f"malformed cell attributes: {error}"]
    cell_id: str | None = None
    attrs: dict[str, str] = {}
    for token in tokens:
        if token.startswith("#"):
            if cell_id is not None:
                errors.append("cell has multiple #id attributes")
            cell_id = token[1:]
        elif "=" in token:
            key, value = token.split("=", 1)
            if key in attrs:
                errors.append(f"duplicate attribute '{key}'")
            attrs[key] = value
        else:
            errors.append(f"malformed attribute '{token}' (expected key=value)")
    return cell_id, attrs, errors


def parse(text: str, path: str | Path | None = None) -> Document:
    frontmatter, body_start, diagnostics = _frontmatter(text)
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)

    cells: list[Cell] = []
    line_index = 0
    while line_index < len(lines) and offsets[line_index] < body_start:
        line_index += 1
    while line_index < len(lines):
        opening = OPEN_FENCE_RE.match(lines[line_index].rstrip("\r\n"))
        if not opening:
            line_index += 1
            continue
        fence = opening.group("fence")
        info = opening.group("info").strip()
        end_index = line_index + 1
        close_re = re.compile(rf"^{re.escape(fence)}\s*$")
        while end_index < len(lines) and not close_re.match(lines[end_index].rstrip("\r\n")):
            end_index += 1
        if end_index == len(lines):
            diagnostics.append(f"line {line_index + 1}: unterminated code fence")
            break
        info_match = ATTR_BLOCK_RE.match(info)
        if info_match:
            attr_block = info_match.group("attrs")
            language = info_match.group("lang").lower()
            if attr_block is None and language in DOCUMENTARY_LANGUAGES:
                line_index = end_index + 1
                continue
            cell_id, attrs, attr_errors = _attributes(attr_block) if attr_block else (None, {}, [])
            # A bare executable fence is intentionally a first-class PMD cell.
            # Generated ids make Markdown-plus-Python useful before users need graph syntax.
            if cell_id is None and not attrs:
                cell_id = f"cell-{len(cells) + 1}"
            if cell_id is not None:
                prefix = cell_id or f"line {line_index + 1}"
                diagnostics.extend(f"{prefix}: {message}" for message in attr_errors)
                source_start = offsets[line_index] + len(lines[line_index])
                source_end = offsets[end_index]
                cells.append(Cell(
                    id=cell_id,
                    language=language,
                    source=text[source_start:source_end].rstrip("\r\n"),
                    attrs=attrs,
                    index=len(cells),
                    start=offsets[line_index],
                    end=offsets[end_index] + len(lines[end_index]),
                ))
        line_index = end_index + 1

    previous: str | None = None
    for cell in cells:
        explicit = cell.attrs.get("depends-on")
        if explicit is not None:
            cell.dependencies = [item.strip() for item in explicit.split(",") if item.strip()]
        elif cell.role in {"code", "setup"} and cell.attrs.get("independent", "false").lower() != "true" and previous:
            cell.dependencies = [previous]
        if cell.role in {"code", "setup"}:
            previous = cell.id
        if cell.role == "test" and cell.attrs.get("test-of"):
            target = cell.attrs["test-of"]
            if target == "document":
                cell.dependencies = list(dict.fromkeys(
                    cell.dependencies + [candidate.id for candidate in cells if candidate.role in {"code", "setup"}]
                ))
            elif target not in cell.dependencies:
                cell.dependencies.append(target)
    return Document(text, frontmatter, cells, diagnostics, Path(path) if path else None, body_start)


def load(path: str | Path) -> Document:
    source_path = Path(path)
    return parse(source_path.read_text(encoding="utf-8"), source_path)
