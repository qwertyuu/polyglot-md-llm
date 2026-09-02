from __future__ import annotations

import os
import re
import shlex
import sys
from collections import Counter
from pathlib import Path

from .models import Cell, Document
from .contracts import literal_ctx_reads, produced_contracts, schema_definitions
from .capabilities import capability_warnings, declared_capabilities
from .parser import ID_RE, KNOWN_ATTRIBUTES, STALE_AFTER_RE

DEFAULT_ENGINES: dict[str, list[str]] = {
    "python": [sys.executable],
    "python3": [sys.executable],
    "bash": ["bash"],
    "sh": ["sh"],
    "pwsh": ["pwsh", "-NoLogo", "-NoProfile", "-Command", "-"],
    "powershell": ["powershell", "-NoLogo", "-NoProfile", "-Command", "-"],
    "sql": [sys.executable, "-m", "pmd_notebook.sql_engine"],
}
ROLES = {"code", "setup", "test", "scratch", "lib"}
BOOLEAN = {"true", "false"}
DURATION_RE = re.compile(r"^[1-9]\d*(?:\.\d+)?[sm]$")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def engines(document: Document) -> tuple[dict[str, list[str]], list[str]]:
    result = {key: list(value) for key, value in DEFAULT_ENGINES.items()}
    errors: list[str] = []
    configured = _project_config(document).get("engines", {})
    configured = {**configured, **(document.frontmatter.get("engines", {}) or {})} if isinstance(configured, dict) else document.frontmatter.get("engines", {})
    if configured is None:
        configured = {}
    if not isinstance(configured, dict):
        return result, ["frontmatter engines must be a mapping"]
    for language, config in configured.items():
        if not isinstance(config, dict) or not isinstance(config.get("command"), str):
            errors.append(f"engine '{language}' must define a string command")
            continue
        try:
            document_dir = document.path.resolve().parent if document.path else Path.cwd()
            command = os.path.expandvars(config["command"]).replace("{document_dir}", str(document_dir)).replace("{project_dir}", str(project_root(document)))
            tokens = shlex.split(command, posix=sys.platform != "win32")
            if sys.platform == "win32":
                tokens = [token[1:-1] if len(token) >= 2 and token[0] == token[-1] == '"' else token for token in tokens]
            if not tokens:
                errors.append(f"engine '{language}' command must not be empty")
                continue
            if tokens and ("/" in tokens[0] or "\\" in tokens[0]) and not Path(tokens[0]).is_absolute():
                tokens[0] = str((document_dir / tokens[0]).resolve())
            result[str(language).lower()] = tokens
        except ValueError as error:
            errors.append(f"engine '{language}' has invalid command: {error}")
    return result, errors


def validate(document: Document) -> list[str]:
    errors = list(document.diagnostics)
    available, engine_errors = engines(document)
    errors.extend(engine_errors)
    inputs = document.frontmatter.get("inputs", [])
    if not isinstance(inputs, (str, list)) or isinstance(inputs, list) and not all(isinstance(item, str) for item in inputs):
        errors.append("frontmatter inputs must be a path string or list of path strings")
    counts = Counter(cell.id for cell in document.cells)
    ids = set(counts)
    lookup = document.lookup
    schemas, schema_errors = schema_definitions(document)
    errors.extend(schema_errors)
    declared, capability_errors = declared_capabilities(document)
    errors.extend(capability_errors)
    errors.extend(capability_warnings(document, declared))
    producers: dict[str, str] = {}
    for candidate in document.cells:
        contracts, contract_errors = produced_contracts(candidate)
        errors.extend(contract_errors)
        for key, schema_name in contracts:
            if schema_name not in schemas:
                errors.append(f"{candidate.id}: unknown schema '{schema_name}' for produced key '{key}'")
            if key in producers:
                errors.append(f"duplicate producer for ctx key '{key}': {producers[key]}, {candidate.id}")
            else:
                producers[key] = candidate.id
    for cell_id, count in counts.items():
        if count > 1:
            errors.append(f"duplicate cell id: {cell_id}")
    for cell in document.cells:
        if not ID_RE.fullmatch(cell.id):
            errors.append(f"invalid cell id: '{cell.id}'")
        for key in cell.attrs:
            if key not in KNOWN_ATTRIBUTES:
                errors.append(f"{cell.id}: unknown attribute '{key}'")
        if "inputs" in cell.attrs and not all(item.strip() for item in cell.attrs["inputs"].split(",")):
            errors.append(f"{cell.id}: inputs must be a comma-separated list of paths")
        if cell.language not in available:
            errors.append(f"{cell.id}: no engine for '{cell.language}'")
        if cell.role not in ROLES:
            errors.append(f"{cell.id}: invalid role '{cell.role}'")
        for key in ("independent", "skip"):
            if key in cell.attrs and cell.attrs[key].lower() not in BOOLEAN:
                errors.append(f"{cell.id}: {key} must be true or false")
        if cell.role not in {"code", "setup"} and "independent" in cell.attrs:
            errors.append(f"{cell.id}: independent does not apply to role={cell.role}")
        if cell.role in {"scratch", "lib"} and "depends-on" in cell.attrs:
            errors.append(f"{cell.id}: depends-on does not apply to role={cell.role}")
        if cell.role == "test" and not cell.attrs.get("test-of"):
            errors.append(f"{cell.id}: test cells require test-of")
        if cell.role != "test" and "test-of" in cell.attrs:
            errors.append(f"{cell.id}: test-of only applies to role=test")
        if cell.role not in {"code", "setup", "test"} and "uses" in cell.attrs:
            errors.append(f"{cell.id}: uses does not apply to role={cell.role}")
        for used in cell.uses:
            if used not in ids:
                errors.append(f"{cell.id}: unresolved reference '{used}'")
                continue
            target = lookup[used]
            if target.role != "lib":
                errors.append(f"{cell.id}: uses reference '{used}' must be role=lib")
            elif target.language != cell.language:
                errors.append(f"{cell.id}: uses reference '{used}' has language '{target.language}', expected '{cell.language}'")
        timeout = cell.attrs.get("timeout")
        if timeout and not DURATION_RE.fullmatch(timeout):
            errors.append(f"{cell.id}: invalid timeout '{timeout}'")
        stale_after = cell.attrs.get("stale-after")
        if stale_after and not STALE_AFTER_RE.fullmatch(stale_after):
            errors.append(f"{cell.id}: invalid stale-after '{stale_after}'")
        if "expect-exit-code" in cell.attrs:
            try:
                int(cell.attrs["expect-exit-code"])
            except ValueError:
                errors.append(f"{cell.id}: expect-exit-code must be an integer")
        for entry in filter(None, (part.strip() for part in cell.attrs.get("env", "").split(","))):
            key = entry.split("=", 1)[0]
            if not ENV_KEY_RE.fullmatch(key):
                errors.append(f"{cell.id}: invalid environment variable '{key}'")
        for dependency in cell.dependencies:
            if dependency not in ids:
                errors.append(f"{cell.id}: unresolved reference '{dependency}'")
        known_dependencies = [dependency for dependency in cell.dependencies if dependency in lookup]
        ancestors = closure(known_dependencies, document) if known_dependencies else set()
        for key in sorted(literal_ctx_reads(cell.source)):
            producer = producers.get(key)
            if producer is not None and producer not in ancestors:
                errors.append(f"{cell.id}: ctx key '{key}' is produced by '{producer}' outside its dependency closure")
    default_timeout = document.frontmatter.get("timeout_default", "60s")
    if not isinstance(default_timeout, str) or not DURATION_RE.fullmatch(default_timeout):
        errors.append(f"invalid timeout_default '{default_timeout}'")
    version = document.frontmatter.get("pmd")
    if version is not None and str(version) != "0.1":
        errors.append(f"warning: unrecognized PMD version '{version}'")
    errors.extend(_cycles(document))
    return list(dict.fromkeys(errors))


def _cycles(document: Document) -> list[str]:
    lookup = document.lookup
    state: dict[str, int] = {}
    errors: list[str] = []

    def visit(cell_id: str, stack: list[str]) -> None:
        if state.get(cell_id) == 1:
            start = stack.index(cell_id)
            errors.append("dependency cycle: " + " -> ".join(stack[start:] + [cell_id]))
            return
        if state.get(cell_id) == 2:
            return
        state[cell_id] = 1
        for dependency in lookup[cell_id].dependencies:
            if dependency in lookup:
                visit(dependency, stack + [cell_id])
        state[cell_id] = 2

    for cell in document.cells:
        visit(cell.id, [])
    return errors


def closure(targets: list[str], document: Document) -> set[str]:
    lookup = document.lookup
    selected: set[str] = set()

    def add(cell_id: str) -> None:
        if cell_id in selected or cell_id not in lookup:
            return
        selected.add(cell_id)
        for dependency in lookup[cell_id].dependencies:
            add(dependency)

    for target in targets:
        add(target)
    return selected


def topological_order(selected: set[str], document: Document) -> list[Cell]:
    lookup = document.lookup
    done: set[str] = set()
    ordered: list[Cell] = []

    def add(cell: Cell) -> None:
        if cell.id in done:
            return
        for dependency in cell.dependencies:
            if dependency in selected:
                add(lookup[dependency])
        done.add(cell.id)
        ordered.append(cell)

    for cell in document.cells:
        if cell.id in selected:
            add(cell)
    return ordered


def graph_lines(document: Document) -> list[str]:
    lines = []
    for cell in document.cells:
        execution = ", ".join(cell.dependencies) or "(root)"
        composition = f"; uses => {', '.join(cell.uses)}" if cell.uses else ""
        lines.append(f"{cell.id}: executes after <- {execution}{composition}")
    return lines


def project_root(document: Document) -> Path:
    """Use an explicit root, otherwise find the nearest project marker."""
    document_dir = document.path.resolve().parent if document.path else Path.cwd()
    configured = document.frontmatter.get("project_root")
    if isinstance(configured, str) and configured:
        value = os.path.expandvars(configured).replace("{document_dir}", str(document_dir))
        root = Path(value)
        return (document_dir / root).resolve() if not root.is_absolute() else root.resolve()
    for candidate in (document_dir, *document_dir.parents):
        if (candidate / "pmd.yaml").exists() or (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate
    return document_dir


def _project_config(document: Document) -> dict:
    config = project_root(document) / "pmd.yaml"
    if not config.exists():
        return {}
    try:
        import yaml
        value = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        return value if isinstance(value, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}
