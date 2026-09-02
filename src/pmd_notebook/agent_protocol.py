from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import secrets
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .graph import closure, engines, topological_order, validate
from .capabilities import declared_capabilities
from .models import Cell, Document, RunResult
from .parser import ID_RE, KNOWN_ATTRIBUTES, parse
from .render import render_cell_text, render_html
from .runner import Runner, _engine_identity, _input_fingerprints

PROTOCOL = "pmd-agent/0.2"
RECEIPT_VERSION = "pmd-verification/0.1"
RUNNER_NAME = "polyglot-pmd"
RUNNER_VERSION = "0.6.2"
DEFAULT_MAX_RESPONSE = 1024 * 1024
TOKEN_LIFETIME_SECONDS = 24 * 60 * 60
EXECUTABLE_ROLES = {"code", "setup"}


@dataclass(slots=True)
class AgentResult:
    response: dict[str, Any]
    exit_code: int
    max_response_bytes: int = DEFAULT_MAX_RESPONSE


class ProtocolError(Exception):
    def __init__(self, code: str, message: str, *, exit_code: int = 2, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.details = details or {}


@dataclass(slots=True)
class SourceFile:
    path: Path
    raw: bytes
    text: str
    bom: bool

    @property
    def revision(self) -> str:
        return digest(self.raw)

    @property
    def newline(self) -> str:
        return "\r\n" if "\r\n" in self.text else "\n"

    def encode(self, text: str) -> bytes:
        payload = text.encode("utf-8")
        return b"\xef\xbb\xbf" + payload if self.bom else payload


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: bytes | str | Any) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8")
    elif isinstance(value, bytes):
        payload = value
    else:
        payload = canonical_json(value)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def diagnostic(
    code: str,
    message: str,
    *,
    cell_id: str | None = None,
    operation_index: int | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "cell_id": cell_id,
        "operation_index": operation_index,
        "details": details or {},
    }


def envelope(
    command: str,
    source: SourceFile | None,
    *,
    ok: bool,
    result: dict[str, Any] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
    revision: str | None = None,
) -> dict[str, Any]:
    document = None
    if source:
        document = {
            "path": source.path.as_posix(),
            "revision": revision or source.revision,
        }
    return {
        "protocol": PROTOCOL,
        "command": command,
        "ok": ok,
        "document": document,
        "warnings": warnings or [],
        "errors": errors or [],
        "result": result,
    }


def error_result(command: str, error: ProtocolError, source: SourceFile | None = None) -> AgentResult:
    details = dict(error.details)
    operation_index = details.pop("operation_index", None)
    response = envelope(
        command,
        source,
        ok=False,
        errors=[diagnostic(error.code, error.message, operation_index=operation_index, details=details)],
    )
    return AgentResult(response, error.exit_code)


def read_source(path: str | Path) -> SourceFile:
    source_path = Path(path).resolve()
    try:
        raw = source_path.read_bytes()
    except FileNotFoundError as error:
        raise ProtocolError("document_not_found", f"document does not exist: {source_path}") from error
    except OSError as error:
        raise ProtocolError("document_not_found", str(error)) from error
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProtocolError("document_invalid", f"document is not UTF-8: {error}") from error
    return SourceFile(source_path, raw, text, bom)


def parsed(source: SourceFile, text: str | None = None) -> Document:
    document = parse(source.text if text is None else text, source.path)
    failures = [item for item in validate(document) if not item.startswith("warning:")]
    if failures:
        raise ProtocolError("document_invalid", "PMD static validation failed", details={"diagnostics": failures})
    return document


def _request_limit(request: dict[str, Any], key: str = "max_response_bytes") -> int:
    value = request.get(key, DEFAULT_MAX_RESPONSE)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1024:
        raise ProtocolError("invalid_request", f"{key} must be an integer of at least 1024")
    return min(value, DEFAULT_MAX_RESPONSE)


def capabilities() -> AgentResult:
    result = {
        "protocol_versions": [PROTOCOL, "pmd-agent/0.1"],
        "profiles": ["reader", "editor", "verifier", "llm-ready"],
        "commands": ["capabilities", "inspect", "apply", "verify", "run_stream"],
        "features": ["rendered_inspection", "named_narrative", "structured_failures", "declared_capabilities", "engine_identity"],
        "operations": [
            "replace_cell_source",
            "insert_cell",
            "delete_cell",
            "rename_cell",
            "set_cell_language",
            "set_cell_attributes",
            "move_cell",
            "replace_narrative",
            "replace_frontmatter",
        ],
        "limits": {
            "max_request_bytes": DEFAULT_MAX_RESPONSE,
            "max_response_bytes": DEFAULT_MAX_RESPONSE,
            "change_token_lifetime_seconds": TOKEN_LIFETIME_SECONDS,
        },
        "engines": ["bash", "powershell", "pwsh", "python", "python3", "sh", "sql"],
        "policy_enforcement": {
            "network": False,
            "filesystem": False,
            "environment": False,
            "runtime": True,
        },
    }
    return AgentResult(envelope("capabilities", None, ok=True, result=result), 0)


def _content(text: str, media_type: str | None = None) -> dict[str, Any]:
    payload = text.encode("utf-8")
    result: dict[str, Any] = {
        "included": True,
        "bytes": len(payload),
        "digest": digest(payload),
        "text": text,
    }
    if media_type:
        result["media_type"] = media_type
    return result


def _omit(content: dict[str, Any], reason: str) -> None:
    content.pop("text", None)
    content["included"] = False
    content["reason"] = reason


def _reverse_graph(document: Document) -> dict[str, list[str]]:
    reverse = {cell.id: [] for cell in document.cells}
    for cell in document.cells:
        for dependency in cell.dependencies:
            if dependency in reverse:
                reverse[dependency].append(cell.id)
    return reverse


def _walk(roots: list[str], edges: dict[str, list[str]], depth: int) -> set[str]:
    selected = set(roots)
    frontier = set(roots)
    for _ in range(depth):
        frontier = {neighbor for node in frontier for neighbor in edges.get(node, [])} - selected
        selected.update(frontier)
    return selected


def _narrative_segments(document: Document) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    slug_counts: dict[str, int] = {}

    def add_interval(start: int, end: int, before_cell: str | None, after_cell: str | None, fallback_id: str) -> None:
        text = document.source[start:end]
        headings = list(re.finditer(r"(?m)^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*(?:\r?\n|$)", text))
        prefix_end = headings[0].start() if headings else len(text)
        if prefix_end:
            segments.append({
                "segment_id": fallback_id,
                "start": start,
                "end": start + prefix_end,
                "before_cell": before_cell,
                "after_cell": after_cell,
                "text": text[:prefix_end],
            })
        for index, heading in enumerate(headings):
            section_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            normalized = unicodedata.normalize("NFKD", heading.group(1)).encode("ascii", "ignore").decode("ascii").lower()
            base_slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "section"
            slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1
            suffix = "" if slug_counts[base_slug] == 1 else f"-{slug_counts[base_slug]}"
            segments.append({
                "segment_id": f"section:{base_slug}{suffix}",
                "start": start + heading.start(),
                "end": start + section_end,
                "before_cell": before_cell,
                "after_cell": after_cell,
                "text": text[heading.start():section_end],
            })

    cursor = document.body_start
    previous: str | None = None
    for cell in document.cells:
        add_interval(cursor, cell.start, cell.id, previous, f"before:{cell.id}")
        cursor = cell.end
        previous = cell.id
    add_interval(cursor, len(document.source), None, previous, "after:last")
    return segments


def _frontmatter_source(source: SourceFile, document: Document) -> str | None:
    if document.body_start == 0:
        return None
    first_end = source.text.find("\n") + 1
    closing_start = source.text.rfind("\n---", 0, document.body_start)
    if closing_start < 0:
        return ""
    return source.text[first_end:closing_start + 1]


def _media_type(language: str) -> str:
    return {
        "python": "text/x-python",
        "python3": "text/x-python",
        "bash": "text/x-shellscript",
        "sh": "text/x-shellscript",
        "pwsh": "text/x-powershell",
        "powershell": "text/x-powershell",
        "sql": "application/sql",
    }.get(language, "text/plain")


def inspect_document(path: str | Path, request: dict[str, Any], *, allow_execution: bool = False) -> AgentResult:
    source: SourceFile | None = None
    try:
        source = read_source(path)
        document = parsed(source)
        max_bytes = _request_limit(request, "max_bytes")
        roots_value = request.get("roots", [])
        if not isinstance(roots_value, list) or not all(isinstance(item, str) for item in roots_value):
            raise ProtocolError("invalid_request", "roots must be an array of cell IDs")
        roots = list(dict.fromkeys(roots_value))
        unknown = [cell_id for cell_id in roots if cell_id not in document.lookup]
        if unknown:
            raise ProtocolError("unknown_cell", f"unknown cell: {unknown[0]}")
        upstream_depth = request.get("upstream_depth", 0)
        downstream_depth = request.get("downstream_depth", 0)
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (upstream_depth, downstream_depth)):
            raise ProtocolError("invalid_request", "graph depths must be non-negative integers")
        dependency_edges = {cell.id: list(cell.dependencies) for cell in document.cells}
        reverse = _reverse_graph(document)
        selected = set(document.lookup) if not roots else _walk(roots, dependency_edges, upstream_depth) | _walk(roots, reverse, downstream_depth)
        if request.get("include_tests", False):
            selected.update(
                cell.id for cell in document.cells
                if cell.role == "test" and (cell.attrs.get("test-of") in selected or any(item in selected for item in cell.dependencies))
            )
        include_source = request.get("include_source", False)
        if not isinstance(include_source, bool):
            raise ProtocolError("invalid_request", "include_source must be boolean")
        include_rendered = request.get("include_rendered", False)
        if not isinstance(include_rendered, bool):
            raise ProtocolError("invalid_request", "include_rendered must be boolean")
        if include_rendered and not allow_execution:
            raise ProtocolError("authorization_required", "rendered inspection requires host execution authorization", exit_code=5)
        narrative_mode = request.get("include_narrative", "none")
        if narrative_mode not in {"none", "adjacent", "all"}:
            raise ProtocolError("invalid_request", "include_narrative must be none, adjacent, or all")

        rendered_results: dict[str, CellResult] = {}
        if include_rendered:
            render_targets = [
                cell.id for cell in document.cells
                if cell.id in selected and cell.role in {"code", "setup", "test"} and not cell.skipped
            ]
            rendered_run = Runner().run(document, targets=render_targets) if render_targets else RunResult(document, [])
            rendered_results = {item.id: item for item in rendered_run.cells}

        cells: list[dict[str, Any]] = []
        for cell in document.cells:
            if cell.id not in selected:
                continue
            explicit = []
            if "depends-on" in cell.attrs:
                explicit = [item.strip() for item in cell.attrs["depends-on"].split(",") if item.strip()]
            tests = [candidate.id for candidate in document.cells if candidate.role == "test" and candidate.attrs.get("test-of") == cell.id]
            source_data = _content(cell.source, _media_type(cell.language))
            if not include_source:
                _omit(source_data, "not_requested")
            rendered_data = _content(render_cell_text(cell, rendered_results.get(cell.id), document), "text/plain") if include_rendered else None
            cells.append({
                "id": cell.id,
                "language": cell.language,
                "role": cell.role,
                "position": cell.index,
                "attributes": dict(cell.attrs),
                "dependencies": {"explicit": explicit, "resolved": list(cell.dependencies)},
                "uses": list(cell.uses),
                "upstream": list(cell.dependencies),
                "downstream": list(reverse[cell.id]),
                "tests": tests,
                "source": source_data,
                "rendered": rendered_data,
                "content_trust": "untrusted",
            })

        narratives: list[dict[str, Any]] = []
        if narrative_mode != "none":
            for segment in _narrative_segments(document):
                adjacent = segment["before_cell"] in selected or segment["after_cell"] in selected
                if narrative_mode == "all" or adjacent:
                    content = _content(segment["text"], "text/markdown")
                    narratives.append({
                        "segment_id": segment["segment_id"],
                        "digest": content["digest"],
                        "before_cell": segment["before_cell"],
                        "after_cell": segment["after_cell"],
                        "content": content,
                        "content_trust": "untrusted",
                    })

        frontmatter_result: dict[str, Any] | None = None
        if request.get("include_frontmatter", False):
            raw_frontmatter = _frontmatter_source(source, document)
            frontmatter_result = {
                "parsed": document.frontmatter,
                "source": _content(raw_frontmatter or "", "application/yaml") if raw_frontmatter is not None else None,
                "content_trust": "untrusted",
            }

        warnings = [diagnostic("pmd_warning", item) for item in validate(document) if item.startswith("warning:")]
        result = {
            "summary": {
                "title": document.frontmatter.get("title"),
                "cell_count": len(document.cells),
                "selected_cell_count": len(cells),
                "capabilities": declared_capabilities(document)[0],
            },
            "frontmatter": frontmatter_result,
            "cells": cells,
            "narrative": narratives,
            "omissions": [],
        }
        response = envelope("inspect", source, ok=True, result=result, warnings=warnings)
        candidates: list[tuple[int, dict[str, Any], str]] = []
        for item in cells:
            if item["source"]["included"]:
                candidates.append((item["source"]["bytes"], item["source"], f"cell:{item['id']}:source"))
            if item["rendered"] and item["rendered"]["included"]:
                candidates.append((item["rendered"]["bytes"], item["rendered"], f"cell:{item['id']}:rendered"))
        for item in narratives:
            candidates.append((item["content"]["bytes"], item["content"], f"narrative:{item['segment_id']}"))
        if frontmatter_result and frontmatter_result["source"]:
            content = frontmatter_result["source"]
            candidates.append((content["bytes"], content, "frontmatter"))
        for _, content, label in sorted(candidates, reverse=True, key=lambda item: item[0]):
            if len(json_bytes(response)) <= max_bytes:
                break
            _omit(content, "response_budget")
            result["omissions"].append({"item": label, "reason": "response_budget"})
        if len(json_bytes(response)) > max_bytes:
            raise ProtocolError("response_budget_too_small", "mandatory inspection metadata exceeds max_bytes")
        return AgentResult(response, 0, max_bytes)
    except ProtocolError as error:
        return error_result("inspect", error, source)


def _require_string(operation: dict[str, Any], key: str) -> str:
    value = operation.get(key)
    if not isinstance(value, str):
        raise ProtocolError("invalid_request", f"operation field '{key}' must be a string")
    return value


def _normalize_newlines(value: str, newline: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)


def _quote_attr(value: str) -> str:
    if value and re.fullmatch(r"[^\s{}]+", value):
        return value
    return json.dumps(value, ensure_ascii=False)


def _cell_header(cell: Cell, *, language: str | None = None, cell_id: str | None = None, attrs: dict[str, str] | None = None, fence: str = "```") -> str:
    selected_attrs = cell.attrs if attrs is None else attrs
    tokens = [f"#{cell.id if cell_id is None else cell_id}"]
    tokens.extend(f"{key}={_quote_attr(value)}" for key, value in selected_attrs.items())
    return f"{fence}{cell.language if language is None else language} {{{' '.join(tokens)}}}"


def _opening_line(text: str, cell: Cell) -> tuple[str, str, int]:
    line_end = text.find("\n", cell.start, cell.end)
    if line_end < 0:
        raise ProtocolError("transaction_invalid", f"cannot locate opening fence for {cell.id}")
    end = line_end + 1
    line = text[cell.start:line_end].rstrip("\r")
    match = re.match(r"^(`{3,})", line)
    if not match:
        raise ProtocolError("transaction_invalid", f"cannot parse opening fence for {cell.id}")
    newline = "\r\n" if text[line_end - 1:line_end + 1] == "\r\n" else "\n"
    return line, newline, end


def _replace_header(text: str, cell: Cell, *, language: str | None = None, cell_id: str | None = None, attrs: dict[str, str] | None = None) -> str:
    opening, newline, opening_end = _opening_line(text, cell)
    fence = re.match(r"^`+", opening).group(0)  # type: ignore[union-attr]
    header = _cell_header(cell, language=language, cell_id=cell_id, attrs=attrs, fence=fence)
    return text[:cell.start] + header + newline + text[opening_end:]


def _render_cell(cell_id: str, language: str, attrs: dict[str, str], source: str, newline: str) -> str:
    runs = [len(match.group(0)) for line in source.splitlines() if (match := re.match(r"^`+", line))]
    fence = "`" * max(3, max(runs, default=0) + 1)
    shell = Cell(cell_id, language, source, attrs, 0, 0, 0)
    body = _normalize_newlines(source, newline)
    return _cell_header(shell, fence=fence) + newline + body + ("" if not body or body.endswith(newline) else newline) + fence + newline


def _replace_source(text: str, cell: Cell, new_source: str, newline: str) -> str:
    opening, cell_newline, opening_end = _opening_line(text, cell)
    existing_fence = re.match(r"^`+", opening).group(0)  # type: ignore[union-attr]
    normalized = _normalize_newlines(new_source, newline)
    runs = [len(match.group(0)) for line in normalized.splitlines() if (match := re.match(r"^`+", line))]
    length = max(len(existing_fence), max(runs, default=0) + 1, 3)
    fence = "`" * length
    info = opening[len(existing_fence):]
    body = normalized + ("" if not normalized or normalized.endswith(newline) else newline)
    closing_start = text.rfind(existing_fence, opening_end, cell.end)
    if closing_start < 0:
        raise ProtocolError("transaction_invalid", f"cannot locate closing fence for {cell.id}")
    closing_end = closing_start + len(existing_fence)
    return text[:cell.start] + fence + info + cell_newline + body + fence + text[closing_end:]


def _placement(operation: dict[str, Any]) -> tuple[str, str | None]:
    present = [key for key in ("before", "after", "at_end") if key in operation]
    if len(present) != 1:
        raise ProtocolError("invalid_request", "operation requires exactly one of before, after, or at_end")
    key = present[0]
    if key == "at_end":
        if operation[key] is not True:
            raise ProtocolError("invalid_request", "at_end must be true")
        return key, None
    return key, _require_string(operation, key)


def _insert_at(text: str, block: str, position: int, newline: str) -> str:
    prefix = "" if position == 0 or text[position - 1] in "\r\n" or block.startswith(("\r", "\n")) else newline
    suffix = "" if position == len(text) or text[position:position + 1] in "\r\n" or block.endswith(("\r", "\n")) else newline
    return text[:position] + prefix + block + suffix + text[position:]


def _operation_error(error: ProtocolError, index: int) -> ProtocolError:
    details = dict(error.details)
    details["operation_index"] = index
    return ProtocolError(error.code, error.message, exit_code=error.exit_code, details=details)


def _apply_operations(source: SourceFile, document: Document, operations: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], set[str], set[str], list[dict[str, Any]]]:
    text = source.text
    normalized: list[dict[str, Any]] = []
    changed_ids: set[str] = set()
    deleted_ids: set[str] = set()
    replaced_narrative: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        try:
            if not isinstance(operation, dict) or not isinstance(operation.get("op"), str):
                raise ProtocolError("invalid_request", "each operation requires a string op")
            name = operation["op"]
            current = parse(text, source.path)
            lookup = current.lookup
            if name == "replace_cell_source":
                cell_id = _require_string(operation, "cell_id")
                if cell_id not in lookup:
                    raise ProtocolError("unknown_cell", f"unknown cell: {cell_id}")
                cell = lookup[cell_id]
                expected = _require_string(operation, "expected_source_digest")
                if digest(cell.source) != expected:
                    raise ProtocolError("operation_precondition_failed", f"source digest mismatch for {cell_id}", exit_code=4)
                new_source = _require_string(operation, "source")
                text = _replace_source(text, cell, new_source, source.newline)
                changed_ids.add(cell_id)
            elif name == "insert_cell":
                cell_id = _require_string(operation, "cell_id")
                language = _require_string(operation, "language").lower()
                cell_source = _require_string(operation, "source")
                if not ID_RE.fullmatch(cell_id):
                    raise ProtocolError("invalid_request", f"invalid cell ID: {cell_id}")
                if cell_id in lookup:
                    raise ProtocolError("transaction_invalid", f"duplicate cell id: {cell_id}")
                attrs_value = operation.get("attributes", {})
                if not isinstance(attrs_value, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in attrs_value.items()):
                    raise ProtocolError("invalid_request", "attributes must map strings to strings")
                placement, target = _placement(operation)
                if target is not None and target not in lookup:
                    raise ProtocolError("unknown_cell", f"unknown placement cell: {target}")
                position = len(text) if placement == "at_end" else lookup[target].start if placement == "before" else lookup[target].end  # type: ignore[index]
                block = _render_cell(cell_id, language, dict(attrs_value), cell_source, source.newline)
                text = _insert_at(text, block, position, source.newline)
                changed_ids.add(cell_id)
            elif name == "delete_cell":
                cell_id = _require_string(operation, "cell_id")
                if cell_id not in lookup:
                    raise ProtocolError("unknown_cell", f"unknown cell: {cell_id}")
                cell = lookup[cell_id]
                if digest(cell.source) != _require_string(operation, "expected_source_digest"):
                    raise ProtocolError("operation_precondition_failed", f"source digest mismatch for {cell_id}", exit_code=4)
                text = text[:cell.start] + text[cell.end:]
                changed_ids.add(cell_id)
                deleted_ids.add(cell_id)
            elif name == "rename_cell":
                cell_id = _require_string(operation, "cell_id")
                new_id = _require_string(operation, "new_cell_id")
                if cell_id not in lookup:
                    raise ProtocolError("unknown_cell", f"unknown cell: {cell_id}")
                if not ID_RE.fullmatch(new_id) or new_id in lookup:
                    raise ProtocolError("transaction_invalid", f"invalid or duplicate new cell id: {new_id}")
                replacements: list[tuple[int, int, str]] = []
                for candidate in current.cells:
                    attrs = dict(candidate.attrs)
                    changed = candidate.id == cell_id
                    if "depends-on" in attrs:
                        dependencies = [new_id if value.strip() == cell_id else value.strip() for value in attrs["depends-on"].split(",")]
                        updated = ",".join(dependencies)
                        changed = changed or updated != attrs["depends-on"]
                        attrs["depends-on"] = updated
                    if attrs.get("test-of") == cell_id:
                        attrs["test-of"] = new_id
                        changed = True
                    if changed:
                        opening, newline, opening_end = _opening_line(text, candidate)
                        fence = re.match(r"^`+", opening).group(0)  # type: ignore[union-attr]
                        header = _cell_header(candidate, cell_id=new_id if candidate.id == cell_id else None, attrs=attrs, fence=fence) + newline
                        replacements.append((candidate.start, opening_end, header))
                for start, end, replacement in reversed(replacements):
                    text = text[:start] + replacement + text[end:]
                changed_ids.discard(cell_id)
                changed_ids.add(new_id)
                deleted_ids.add(cell_id)
            elif name == "set_cell_language":
                cell_id = _require_string(operation, "cell_id")
                language = _require_string(operation, "language").lower()
                if cell_id not in lookup:
                    raise ProtocolError("unknown_cell", f"unknown cell: {cell_id}")
                text = _replace_header(text, lookup[cell_id], language=language)
                changed_ids.add(cell_id)
            elif name == "set_cell_attributes":
                cell_id = _require_string(operation, "cell_id")
                if cell_id not in lookup:
                    raise ProtocolError("unknown_cell", f"unknown cell: {cell_id}")
                set_value = operation.get("set", {})
                remove = operation.get("remove", [])
                if not isinstance(set_value, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in set_value.items()):
                    raise ProtocolError("invalid_request", "set must map strings to strings")
                if not isinstance(remove, list) or not all(isinstance(item, str) for item in remove):
                    raise ProtocolError("invalid_request", "remove must be an array of strings")
                if set(set_value) & set(remove):
                    raise ProtocolError("invalid_request", "an attribute cannot be set and removed")
                unknown = (set(set_value) | set(remove)) - KNOWN_ATTRIBUTES
                if unknown:
                    raise ProtocolError("transaction_invalid", f"unknown attribute: {sorted(unknown)[0]}")
                attrs = dict(lookup[cell_id].attrs)
                for key in remove:
                    attrs.pop(key, None)
                attrs.update(set_value)
                text = _replace_header(text, lookup[cell_id], attrs=attrs)
                changed_ids.add(cell_id)
            elif name == "move_cell":
                cell_id = _require_string(operation, "cell_id")
                if cell_id not in lookup:
                    raise ProtocolError("unknown_cell", f"unknown cell: {cell_id}")
                placement, target = _placement(operation)
                if target == cell_id:
                    raise ProtocolError("invalid_request", "a cell cannot be moved relative to itself")
                cell = lookup[cell_id]
                block = text[cell.start:cell.end]
                without = text[:cell.start] + text[cell.end:]
                remaining = parse(without, source.path)
                if target is not None and target not in remaining.lookup:
                    raise ProtocolError("unknown_cell", f"unknown placement cell: {target}")
                position = len(without) if placement == "at_end" else remaining.lookup[target].start if placement == "before" else remaining.lookup[target].end  # type: ignore[index]
                text = _insert_at(without, block, position, source.newline)
                changed_ids.add(cell_id)
            elif name == "replace_narrative":
                segment_id = _require_string(operation, "segment_id")
                segment = next((item for item in _narrative_segments(current) if item["segment_id"] == segment_id), None)
                if not segment:
                    raise ProtocolError("operation_precondition_failed", f"unknown narrative segment: {segment_id}", exit_code=4)
                if digest(segment["text"]) != _require_string(operation, "expected_digest"):
                    raise ProtocolError("operation_precondition_failed", f"narrative digest mismatch: {segment_id}", exit_code=4)
                replaced_narrative.append({
                    "segment_id": segment_id,
                    "before_cell": segment["before_cell"],
                    "after_cell": segment["after_cell"],
                    "text": segment["text"],
                })
                markdown = _normalize_newlines(_require_string(operation, "markdown"), source.newline)
                candidate_text = text[:segment["start"]] + markdown + text[segment["end"]:]
                if set(parse(candidate_text, source.path).lookup) - set(current.lookup):
                    raise ProtocolError("transaction_invalid", "replace_narrative cannot create executable cells")
                text = candidate_text
            elif name == "replace_frontmatter":
                expected = operation.get("expected_digest")
                yaml_source = _require_string(operation, "yaml")
                existing = _frontmatter_source(source, current) if current.source == source.text else _frontmatter_source(SourceFile(source.path, b"", text, source.bom), current)
                if expected is not None and not isinstance(expected, str):
                    raise ProtocolError("invalid_request", "expected_digest must be a string or null")
                if (digest(existing) if existing is not None else None) != expected:
                    raise ProtocolError("operation_precondition_failed", "frontmatter digest mismatch", exit_code=4)
                if yaml_source:
                    normalized_yaml = _normalize_newlines(yaml_source, source.newline)
                    normalized_yaml += "" if normalized_yaml.endswith(source.newline) else source.newline
                    replacement = f"---{source.newline}{normalized_yaml}---{source.newline}"
                else:
                    replacement = ""
                text = replacement + text[current.body_start:]
            else:
                raise ProtocolError("unsupported_capability", f"unsupported operation: {name}")
            normalized.append({"index": index, "op": name, "status": "applied"})
        except ProtocolError as error:
            raise _operation_error(error, index) from error
    return text, normalized, changed_ids, deleted_ids, replaced_narrative


def _impact_from_changed(document: Document, changed_ids: set[str], *, document_wide: bool = False) -> dict[str, Any]:
    reverse = _reverse_graph(document)
    directly_changed = [cell.id for cell in document.cells if cell.id in changed_ids]
    executable_seeds = [cell.id for cell in document.cells if cell.id in changed_ids and cell.role in EXECUTABLE_ROLES]
    affected_set = set(cell.id for cell in document.cells if cell.role in EXECUTABLE_ROLES) if document_wide else _walk(executable_seeds, reverse, len(document.cells))
    affected_set = {cell_id for cell_id in affected_set if document.lookup[cell_id].role in EXECUTABLE_ROLES}
    impacted_tests: list[str] = []
    for cell in document.cells:
        if cell.role != "test":
            continue
        test_closure = closure([cell.id], document)
        if cell.id in changed_ids or cell.attrs.get("test-of") in affected_set or test_closure & affected_set:
            impacted_tests.append(cell.id)
    return {
        "directly_changed": directly_changed,
        "dependency_changed": [],
        "affected": [cell.id for cell in document.cells if cell.id in affected_set],
        "impacted_tests": impacted_tests,
        "unaffected": [cell.id for cell in document.cells if cell.id not in affected_set and cell.role in EXECUTABLE_ROLES],
        "confidence": "structural",
        "undeclared_state_possible": True,
        "reasons": ["host_filesystem_visible", "network_access_not_enforced"],
    }


def _impact(old: Document, new: Document, requested_changed: set[str], deleted: set[str]) -> dict[str, Any]:
    old_lookup = old.lookup
    directly = set(requested_changed)
    dependency_changed: set[str] = set()
    for cell in new.cells:
        previous = old_lookup.get(cell.id)
        if previous and previous.dependencies != cell.dependencies:
            dependency_changed.add(cell.id)
    frontmatter_changed = old.frontmatter != new.frontmatter
    execution_keys = {"pmd", "engines", "inputs", "ctx", "timeout_default", "agent"}
    document_wide = any(old.frontmatter.get(key) != new.frontmatter.get(key) for key in execution_keys)
    result = _impact_from_changed(new, directly | dependency_changed, document_wide=document_wide)
    result["directly_changed"] = [cell.id for cell in new.cells if cell.id in directly] + sorted(deleted)
    result["dependency_changed"] = [cell.id for cell in new.cells if cell.id in dependency_changed]
    result["frontmatter_changed"] = frontmatter_changed
    result["document_wide"] = document_wide
    return result


class ChangeStore:
    def __init__(self) -> None:
        configured = os.environ.get("PMD_AGENT_STATE_DIR")
        if configured:
            self.directory = Path(configured)
        else:
            cache = Path(os.environ.get("PMD_CACHE_DIR", Path.home() / ".cache" / "polyglot-pmd"))
            self.directory = cache / "agent-tokens"

    def create(self, source: SourceFile, new_revision: str, operations: list[dict[str, Any]], impact: dict[str, Any]) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        canonical_path = str(source.path.resolve())
        for path in self.directory.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("path") == canonical_path:
                    path.unlink(missing_ok=True)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        token = secrets.token_urlsafe(32)
        record = {
            "token": token,
            "path": canonical_path,
            "base_revision": source.revision,
            "new_revision": new_revision,
            "operations": operations,
            "impact": impact,
            "created_at": time.time(),
            "expires_at": time.time() + TOKEN_LIFETIME_SECONDS,
        }
        temporary = self.directory / f".{token}.tmp"
        temporary.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(self.directory / f"{token}.json")
        return token

    def load(self, token: str, source: SourceFile) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            raise ProtocolError("operation_precondition_failed", "invalid or expired change token", exit_code=4)
        try:
            record = json.loads((self.directory / f"{token}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ProtocolError("operation_precondition_failed", "invalid or expired change token", exit_code=4) from error
        if record.get("path") != str(source.path.resolve()) or record.get("new_revision") != source.revision or record.get("expires_at", 0) < time.time():
            raise ProtocolError("operation_precondition_failed", "change token does not match the current document", exit_code=4)
        return record

    def delete(self, token: str) -> None:
        (self.directory / f"{token}.json").unlink(missing_ok=True)


def _bounded_diff(old: str, new: str, old_name: str, new_name: str, budget: int) -> dict[str, Any]:
    unified = "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True), fromfile=old_name, tofile=new_name))
    content = _content(unified, "text/x-diff")
    if content["bytes"] > max(1024, budget // 2):
        _omit(content, "response_budget")
    return content


def apply_transaction(path: str | Path, request: dict[str, Any]) -> AgentResult:
    source: SourceFile | None = None
    try:
        source = read_source(path)
        document = parsed(source)
        max_bytes = _request_limit(request)
        base_revision = request.get("base_revision")
        if not isinstance(base_revision, str):
            raise ProtocolError("invalid_request", "base_revision is required")
        if source.revision != base_revision:
            raise ProtocolError("revision_conflict", "document changed after inspection", exit_code=4, details={"expected": base_revision, "actual": source.revision})
        operations = request.get("operations")
        if not isinstance(operations, list) or not operations:
            raise ProtocolError("invalid_request", "operations must be a non-empty array")
        if not all(isinstance(item, dict) for item in operations):
            raise ProtocolError("invalid_request", "each operation must be an object")
        candidate, normalized, changed_ids, deleted_ids, replaced_narrative = _apply_operations(source, document, operations)
        candidate_document = parse(candidate, source.path)
        failures = [item for item in validate(candidate_document) if not item.startswith("warning:")]
        if failures:
            code = "dependent_cells_exist" if any("unresolved reference" in item and any(deleted in item for deleted in deleted_ids) for item in failures) else "transaction_invalid"
            raise ProtocolError(code, "candidate PMD document is invalid", details={"diagnostics": failures})
        impact = _impact(document, candidate_document, changed_ids, deleted_ids)
        candidate_raw = source.encode(candidate)
        new_revision = digest(candidate_raw)
        dry_run = request.get("dry_run", False)
        if not isinstance(dry_run, bool):
            raise ProtocolError("invalid_request", "dry_run must be boolean")
        diff_content = _bounded_diff(source.text, candidate, source.path.name, source.path.name, max_bytes)
        narrative_evidence = [
            {
                "segment_id": item["segment_id"],
                "before_cell": item["before_cell"],
                "after_cell": item["after_cell"],
                "content": _content(item["text"], "text/markdown"),
            }
            for item in replaced_narrative
        ]
        placeholder_token = None if dry_run else "x" * 43
        recommended = {
            "document_revision": new_revision,
            "change_token": placeholder_token,
            "include_downstream": True,
            "tests": "impacted",
            "fresh": False,
        }
        result = {
            "applied": not dry_run,
            "dry_run": dry_run,
            "base_revision": source.revision,
            "new_revision": new_revision,
            "change_token": placeholder_token,
            "operations": normalized,
            "changed_cells": impact["directly_changed"],
            "changed_narrative": [item.get("segment_id") for item in operations if item.get("op") == "replace_narrative"],
            "replaced_narrative": narrative_evidence,
            "normalizations": [],
            "diff": diff_content,
            "impact": impact,
            "recommended_verification": recommended,
        }
        response_revision = source.revision if dry_run else new_revision
        prospective = envelope("apply", source, ok=True, result=result, revision=response_revision)
        if len(json_bytes(prospective)) > max_bytes and diff_content["included"]:
            _omit(diff_content, "response_budget")
        for item in narrative_evidence:
            if len(json_bytes(prospective)) <= max_bytes:
                break
            if item["content"]["included"]:
                _omit(item["content"], "response_budget")
        if len(json_bytes(prospective)) > max_bytes:
            raise ProtocolError("response_budget_too_small", "mandatory apply metadata exceeds max_response_bytes")

        token: str | None = None
        if not dry_run:
            current = source.path.read_bytes()
            if digest(current) != source.revision:
                raise ProtocolError("revision_conflict", "document changed while applying transaction", exit_code=4)
            store = ChangeStore()
            try:
                token = store.create(source, new_revision, operations, impact)
            except OSError as error:
                raise ProtocolError("internal_error", f"cannot persist change token: {error}", exit_code=6) from error
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(prefix=f".{source.path.name}.", suffix=".tmp", dir=source.path.parent, delete=False) as stream:
                    stream.write(candidate_raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                    temporary_path = Path(stream.name)
                os.chmod(temporary_path, source.path.stat().st_mode)
                os.replace(temporary_path, source.path)
            except OSError as error:
                store.delete(token)
                raise ProtocolError("internal_error", f"cannot commit transaction: {error}", exit_code=6) from error
            finally:
                if temporary_path:
                    temporary_path.unlink(missing_ok=True)
        result["change_token"] = token
        recommended["change_token"] = token
        response = envelope("apply", source, ok=True, result=result, revision=response_revision)
        return AgentResult(response, 0, max_bytes)
    except ProtocolError as error:
        return error_result("apply", error, source)


def _iso_timestamp(timestamp: float | None = None) -> str:
    return datetime.fromtimestamp(timestamp or time.time(), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _plan(document: Document, impact: dict[str, Any], request: dict[str, Any]) -> tuple[dict[str, Any], list[str], bool]:
    include_downstream = request.get("include_downstream", True)
    if not isinstance(include_downstream, bool):
        raise ProtocolError("invalid_request", "include_downstream must be boolean")
    changed = set(impact["directly_changed"])
    affected = list(impact["affected"])
    targets = affected if include_downstream else [cell.id for cell in document.cells if cell.id in changed and cell.role in EXECUTABLE_ROLES]
    tests_mode = request.get("tests", "impacted")
    if tests_mode not in {"none", "impacted", "all"}:
        raise ProtocolError("invalid_request", "tests must be none, impacted, or all")
    planned_tests = [] if tests_mode == "none" else impact["impacted_tests"] if tests_mode == "impacted" else [cell.id for cell in document.cells if cell.role == "test"]
    targets = list(dict.fromkeys(targets + planned_tests))
    for key in ("fresh", "render"):
        if key in request and not isinstance(request[key], bool):
            raise ProtocolError("invalid_request", f"{key} must be boolean")
    selected = closure(targets, document) if targets else set()
    order = [cell.id for cell in topological_order(selected, document)]
    available, _ = engines(document)
    input_fingerprints = _input_fingerprints(document)
    limits = request.get("limits", {})
    if not isinstance(limits, dict):
        raise ProtocolError("invalid_request", "limits must be an object")
    max_cells = limits.get("max_cells")
    if max_cells is not None and (not isinstance(max_cells, int) or isinstance(max_cells, bool) or max_cells < 0):
        raise ProtocolError("invalid_request", "limits.max_cells must be a non-negative integer")
    for key in ("max_runtime_seconds", "max_output_bytes"):
        value = limits.get(key)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0):
            raise ProtocolError("invalid_request", f"limits.{key} must be a non-negative number")
    blocked_limit = max_cells is not None and len(order) > max_cells
    request_restrictions = request.get("restrictions", {})
    if not isinstance(request_restrictions, dict):
        raise ProtocolError("invalid_request", "restrictions must be an object")
    agent_metadata = document.frontmatter.get("agent", {})
    if agent_metadata is None:
        agent_metadata = {}
    if not isinstance(agent_metadata, dict):
        raise ProtocolError("document_invalid", "frontmatter agent must be a mapping")
    document_restrictions = agent_metadata.get("restrictions", {})
    if not isinstance(document_restrictions, dict):
        raise ProtocolError("document_invalid", "frontmatter agent.restrictions must be a mapping")
    restrictions = dict(request_restrictions)
    for key, value in document_restrictions.items():
        if key not in restrictions or value == "deny":
            restrictions[key] = value
    unsupported_restrictions = []
    if restrictions.get("network") == "deny":
        unsupported_restrictions.append("network")
    if "filesystem" in restrictions:
        unsupported_restrictions.append("filesystem")
    if "environment_allow" in restrictions:
        unsupported_restrictions.append("environment")
    policy = {
        "host": "configured_out_of_band",
        "document_restrictions": document_restrictions,
        "request_restrictions": request_restrictions,
        "effective": restrictions,
        "enforced": not unsupported_restrictions,
        "unenforced": unsupported_restrictions,
    }
    plan = {
        "document_revision": digest(document.source),
        "changed_cells": [cell.id for cell in document.cells if cell.id in changed],
        "affected_cells": affected,
        "tests": planned_tests,
        "targets": targets,
        "execution_order": order,
        "engines": {cell.id: available[cell.language] for cell in document.cells if cell.id in selected},
        "engine_identities": {cell.id: _engine_identity(available[cell.language]) for cell in document.cells if cell.id in selected},
        "inputs": [{"path": path.replace("\\", "/"), "digest": f"sha256:{value}"} for path, value in sorted(input_fingerprints.items())],
        "fresh": request.get("fresh", False),
        "render": request.get("render", False),
        "limits": limits,
        "policy": policy,
        "declared_capabilities": declared_capabilities(document)[0],
        "omissions": [],
    }
    plan["plan_id"] = digest(plan)
    incomplete = (not include_downstream and set(affected) - set(targets)) or (tests_mode == "none" and impact["impacted_tests"])
    return plan, targets, bool(incomplete or blocked_limit)


def _receipt(
    source: SourceFile,
    plan: dict[str, Any],
    status: str,
    started: float,
    *,
    scope_source: str,
    run: RunResult | None = None,
    omissions: list[dict[str, Any]] | None = None,
    rendered: str | None = None,
) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    blocked_result = next((item for item in run.cells if item.status == "blocked"), None) if run else None
    receipt_reason = None
    receipt_detail: dict[str, Any] = {}
    if blocked_result is not None:
        receipt_reason = blocked_result.stderr or "cell execution was blocked"
        receipt_detail = {"cell_id": blocked_result.id, "message": receipt_reason}
    elif omissions:
        receipt_reason = str(omissions[0].get("reason") or "verification was blocked")
        receipt_detail = dict(omissions[0])
    if run:
        for result in run.cells:
            cell = run.document.lookup[result.id]
            evidence = {
                "cell_id": result.id,
                "role": cell.role,
                "language": cell.language,
                "source_digest": digest(cell.source),
                "dependencies": list(cell.dependencies),
                "command": result.command,
                "engine_identity": _engine_identity(result.command),
                "status": result.status,
                "cached": result.cached,
                "cache_key": result.cache_key,
                "started_at": result.started_at,
                "duration_seconds": result.duration_seconds,
                "exit_code": result.exit_code,
                "expected_exit_code": int(cell.attrs.get("expect-exit-code", "0")),
                "stdout": {"bytes": len(result.stdout.encode()), "digest": digest(result.stdout)},
                "stderr": {"bytes": len(result.stderr.encode()), "digest": digest(result.stderr)},
                "outputs": [
                    {"name": output.name, "media_type": output.kind, "bytes": len(output.data), "digest": digest(output.data)}
                    for output in result.outputs
                ],
                "context": [{"key": key, "digest": digest(value)} for key, value in sorted(result.context.items())],
                "failure": result.failure,
            }
            (tests if cell.role == "test" else cells).append(evidence)
    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "receipt_id": None,
        "status": status,
        "reason": receipt_reason if status == "blocked" else None,
        "detail": receipt_detail if status == "blocked" else {},
        "document_revision": source.revision,
        "plan_id": plan["plan_id"],
        "scope_source": scope_source,
        "runner": {"name": RUNNER_NAME, "version": RUNNER_VERSION},
        "started_at": _iso_timestamp(started),
        "finished_at": _iso_timestamp(),
        "policy": plan["policy"],
        "inputs": plan["inputs"],
        "cells": cells,
        "tests": tests,
        "render": {"bytes": len(rendered.encode()), "digest": digest(rendered)} if rendered is not None else None,
        "omissions": omissions or [],
        "claims": {
            "static_validation": True,
            "planned_scope_complete": status == "verified",
            "declared_inputs_unchanged": status == "verified",
            "undeclared_state_possible": True,
        },
    }
    receipt["receipt_id"] = digest({key: value for key, value in receipt.items() if key != "receipt_id"})
    return receipt


def verify_document(path: str | Path, request: dict[str, Any], *, allow_execution: bool) -> AgentResult:
    source: SourceFile | None = None
    started = time.time()
    try:
        source = read_source(path)
        document = parsed(source)
        max_bytes = _request_limit(request)
        expected_revision = request.get("document_revision")
        if not isinstance(expected_revision, str):
            raise ProtocolError("invalid_request", "document_revision is required")
        if expected_revision != source.revision:
            raise ProtocolError("revision_conflict", "document changed before verification", exit_code=4, details={"expected": expected_revision, "actual": source.revision})
        has_token = "change_token" in request
        has_cells = "changed_cells" in request
        if has_token == has_cells:
            raise ProtocolError("invalid_request", "provide exactly one of change_token or changed_cells")
        if has_token:
            token = request["change_token"]
            if not isinstance(token, str):
                raise ProtocolError("invalid_request", "change_token must be a string")
            record = ChangeStore().load(token, source)
            impact = record["impact"]
            scope_source = "apply_transaction"
        else:
            values = request["changed_cells"]
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise ProtocolError("invalid_request", "changed_cells must be an array of cell IDs")
            unknown = [value for value in values if value not in document.lookup]
            if unknown:
                raise ProtocolError("unknown_cell", f"unknown cell: {unknown[0]}")
            impact = _impact_from_changed(document, set(values))
            scope_source = "caller_asserted"
        try:
            plan, targets, incomplete = _plan(document, impact, request)
        except OSError as error:
            raise ProtocolError("document_invalid", str(error)) from error
        plan["document_revision"] = source.revision
        plan["plan_id"] = digest({key: value for key, value in plan.items() if key != "plan_id"})
        if not allow_execution and targets:
            receipt = _receipt(source, plan, "blocked", started, scope_source=scope_source, omissions=[{"reason": "authorization_required"}])
            response = envelope("verify", source, ok=False, result={"plan": plan, "receipt": receipt}, errors=[diagnostic("authorization_required", "host execution authorization is required")])
            return AgentResult(response, 5, max_bytes)
        if plan["policy"]["unenforced"]:
            receipt = _receipt(source, plan, "blocked", started, scope_source=scope_source, omissions=[{"reason": "policy_unenforceable", "features": plan["policy"]["unenforced"]}])
            response = envelope("verify", source, ok=False, result={"plan": plan, "receipt": receipt}, errors=[diagnostic("policy_unenforceable", "runner cannot enforce requested restrictions")])
            return AgentResult(response, 5, max_bytes)
        max_cells = plan["limits"].get("max_cells")
        if max_cells is not None and len(plan["execution_order"]) > max_cells:
            receipt = _receipt(source, plan, "blocked", started, scope_source=scope_source, omissions=[{"reason": "limit_exceeded", "limit": "max_cells"}])
            response = envelope("verify", source, ok=False, result={"plan": plan, "receipt": receipt}, errors=[diagnostic("limit_exceeded", "verification plan exceeds max_cells")])
            return AgentResult(response, 5, max_bytes)
        before_inputs = {item["path"]: item["digest"] for item in plan["inputs"]}
        run = Runner().run(document, targets=targets, fresh=request.get("fresh", False)) if targets else RunResult(document, [])
        current = read_source(source.path)
        if current.revision != source.revision:
            receipt = _receipt(source, plan, "blocked", started, scope_source=scope_source, run=run, omissions=[{"reason": "document_changed_during_verification"}])
            response = envelope("verify", current, ok=False, result={"plan": plan, "receipt": receipt}, errors=[diagnostic("document_changed_during_verification", "document changed during verification")])
            return AgentResult(response, 5, max_bytes)
        try:
            after_inputs = {path.replace("\\", "/"): f"sha256:{value}" for path, value in _input_fingerprints(document).items()}
        except OSError:
            after_inputs = {}
        if before_inputs != after_inputs:
            receipt = _receipt(source, plan, "blocked", started, scope_source=scope_source, run=run, omissions=[{"reason": "required_input_changed"}])
            response = envelope("verify", source, ok=False, result={"plan": plan, "receipt": receipt}, errors=[diagnostic("required_input_changed", "a declared input changed during verification")])
            return AgentResult(response, 5, max_bytes)
        rendered: str | None = None
        if request.get("render", False) and run.ok:
            rendered, _ = render_html(document, run)
        max_output = plan["limits"].get("max_output_bytes")
        output_size = sum(len(cell.stdout.encode()) + len(cell.stderr.encode()) + sum(len(item.data) for item in cell.outputs) for cell in run.cells)
        runtime_limit = plan["limits"].get("max_runtime_seconds")
        over_limit = max_output is not None and output_size > max_output or runtime_limit is not None and time.time() - started > runtime_limit
        execution_failed = any(cell.status == "failed" for cell in run.cells)
        execution_blocked = any(cell.status == "blocked" for cell in run.cells)
        status = "failed" if execution_failed else "blocked" if execution_blocked else "incomplete" if incomplete or over_limit else "verified"
        omissions = []
        if incomplete:
            omissions.append({"reason": "requested_scope_incomplete"})
        if over_limit:
            omissions.append({"reason": "limit_exceeded"})
        receipt = _receipt(source, plan, status, started, scope_source=scope_source, run=run, omissions=omissions, rendered=rendered)
        errors: list[dict[str, Any]] = []
        exit_code = 0
        if status == "blocked":
            blocked_cell = next(cell for cell in run.cells if cell.status == "blocked")
            reason = blocked_cell.stderr or "cell execution was blocked"
            errors.append(diagnostic(
                "policy_blocked",
                f"verification was blocked: {reason}",
                cell_id=blocked_cell.id,
                details={"reason": reason},
            ))
            exit_code = 5
        elif status == "failed":
            failing_test = next((cell for cell in run.cells if cell.status == "failed" and document.lookup[cell.id].role == "test"), None)
            code = "test_failed" if failing_test else "cell_failed"
            failing_cell = failing_test or next((cell for cell in run.cells if cell.status == "failed"), None)
            errors.append(diagnostic(code, "verification execution failed", cell_id=failing_cell.id if failing_cell else None, details=failing_cell.failure if failing_cell else None))
            exit_code = 1
        elif status == "incomplete":
            errors.append(diagnostic("limit_exceeded" if over_limit else "invalid_request", "verification scope is incomplete"))
            exit_code = 1
        response = envelope("verify", source, ok=status == "verified", result={"plan": plan, "receipt": receipt}, errors=errors)
        if len(json_bytes(response)) > max_bytes:
            raise ProtocolError("response_budget_too_small", "mandatory verification evidence exceeds max_response_bytes")
        return AgentResult(response, exit_code, max_bytes)
    except ProtocolError as error:
        return error_result("verify", error, source)
