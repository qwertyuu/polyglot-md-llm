from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .bindings import source_with_binding
from .contracts import produced_contracts, schema_definitions, validate_value
from .graph import closure, engines, project_root, topological_order, validate
from .models import Cell, CellResult, Document, RichOutput, RunResult


def _duration(value: str) -> float:
    amount = float(value[:-1])
    return amount * (60 if value.endswith("m") else 1)


def _universal_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _cell_environment(
    cell: Cell,
    output: Path,
    context: Path,
    dependency_outputs: dict[str, Path], project_dir: Path,
    rendered_text: Path | None = None,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({
        "PMD_CELL_OUT": str(output),
        "PMD_CTX_FILE": str(context),
        "PMD_DEP_OUTPUTS": json.dumps({key: str(value) for key, value in dependency_outputs.items()}),
        "PMD_PROJECT_ROOT": str(project_dir),
        "PYTHONUTF8": "1",
    })
    if rendered_text is not None:
        environment["PMD_RENDERED_TEXT_FILE"] = str(rendered_text)
    for entry in filter(None, (part.strip() for part in cell.attrs.get("env", "").split(","))):
        if "=" in entry:
            key, value = entry.split("=", 1)
            environment[key] = value
        elif entry in os.environ:
            environment[entry] = os.environ[entry]
    return environment


def _scan_outputs(output_dir: Path) -> list[RichOutput]:
    outputs: list[RichOutput] = []
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        suffix = path.suffix.lower()
        kind = "image" if suffix in {".png", ".jpg", ".jpeg", ".svg"} else "csv" if suffix == ".csv" else "markdown" if suffix == ".md" else "attachment"
        outputs.append(RichOutput(path.relative_to(output_dir).as_posix(), kind, path.read_bytes()))
    return outputs


def _write_outputs(outputs: list[RichOutput], directory: Path) -> None:
    root = directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for output in outputs:
        destination = (root / output.name).resolve()
        if root != destination and root not in destination.parents:
            raise ValueError(f"unsafe rich output name: {output.name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(output.data)


def _declared_inputs(document: Document) -> list[Path]:
    configured = document.frontmatter.get("inputs", [])
    values = [configured] if isinstance(configured, str) else configured
    values = list(values or []) + [value for cell in document.cells for value in cell.attrs.get("inputs", "").split(",") if value.strip()]
    document_dir = document.path.resolve().parent if document.path else Path.cwd()
    paths: list[Path] = []
    for value in values:
        expanded = os.path.expandvars(value.strip()).replace("{document_dir}", str(document_dir)).replace("{project_dir}", str(project_root(document)))
        path = Path(expanded)
        paths.append((document_dir / path).resolve() if not path.is_absolute() else path.resolve())
    return paths


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()

    def add_file(file_path: Path) -> None:
        with file_path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)

    if path.is_file():
        add_file(path)
        return digest.hexdigest()
    if path.is_dir():
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            digest.update(child.relative_to(path).as_posix().encode())
            add_file(child)
        return digest.hexdigest()
    raise FileNotFoundError(f"declared PMD input does not exist: {path}")


def _input_fingerprints(document: Document) -> dict[str, str]:
    return {str(path): _fingerprint(path) for path in _declared_inputs(document)}


def _engine_identity(command: list[str]) -> dict[str, Any]:
    executable = shutil.which(command[0]) or command[0]
    path = Path(executable).resolve()
    version = None
    try:
        probe = subprocess.run([str(path), "--version"], capture_output=True, timeout=2)
        version = (probe.stdout or probe.stderr).decode("utf-8", errors="replace").splitlines()[0].strip() or None
    except (OSError, subprocess.TimeoutExpired, IndexError):
        pass
    try:
        stat = path.stat()
        file_identity = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    except OSError:
        file_identity = None
    return {"executable": str(path), "version": version, "file": file_identity}


class Cache:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or Path(os.environ.get("PMD_CACHE_DIR", Path.home() / ".cache" / "polyglot-pmd"))

    def key(
        self,
        cell: Cell,
        command: list[str],
        context: dict[str, Any],
        bound_source: str,
        inputs: dict[str, str] | None = None,
    ) -> str:
        payload = {
            "source": cell.source,
            "bound_source": bound_source,
            "attrs": cell.attrs,
            "language": cell.language,
            "command": command,
            "engine_identity": _engine_identity(command),
            "context": context,
            "inputs": inputs or {},
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def load(self, key: str, cell_id: str, command: list[str]) -> CellResult | None:
        path = self.directory / f"{key}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return CellResult(
                id=cell_id, status="cached", command=command, stdout=data["stdout"], stderr=data["stderr"],
                exit_code=data["exit_code"], context=data["context"], cached=True,
                outputs=[RichOutput(item["name"], item["kind"], base64.b64decode(item["data"])) for item in data["outputs"]],
                cache_key=key,
                started_at=data.get("started_at"), duration_seconds=data.get("duration_seconds"),
            )
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return None

    def _freshness_path(self, document: Document, cell: Cell) -> Path:
        identity = str(document.path.resolve()) if document.path else hashlib.sha256(document.source.encode("utf-8")).hexdigest()
        document_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return self.directory / "freshness" / document_key / f"{cell.id}.json"

    def store(self, key: str, result: CellResult, document: Document | None = None, cell: Cell | None = None) -> None:
        if result.status != "passed":
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        data = {
            "stdout": result.stdout, "stderr": result.stderr, "exit_code": result.exit_code, "context": result.context,
            "outputs": [{"name": item.name, "kind": item.kind, "data": base64.b64encode(item.data).decode("ascii")} for item in result.outputs],
            "started_at": result.started_at, "duration_seconds": result.duration_seconds,
        }
        temporary = self.directory / f".{key}.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(self.directory / f"{key}.json")
        if document is not None and cell is not None:
            freshness = self._freshness_path(document, cell)
            freshness.parent.mkdir(parents=True, exist_ok=True)
            record = {"cell_id": cell.id, "source_digest": hashlib.sha256(cell.source.encode("utf-8")).hexdigest(), "started_at": result.started_at, "cache_key": key}
            fresh_temporary = freshness.with_suffix(f".{os.getpid()}.tmp")
            fresh_temporary.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
            fresh_temporary.replace(freshness)

    def freshness(self, document: Document, cell: Cell) -> dict[str, Any] | None:
        try:
            record = json.loads(self._freshness_path(document, cell).read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        expected = hashlib.sha256(cell.source.encode("utf-8")).hexdigest()
        return record if record.get("source_digest") == expected else None

    def stale_warnings(self, document: Document) -> list[str]:
        warnings: list[str] = []
        now = datetime.now(timezone.utc)
        for cell in document.cells:
            threshold = cell.attrs.get("stale-after")
            if not threshold:
                continue
            record = self.freshness(document, cell)
            if not record or not record.get("started_at"):
                warnings.append(f"warning: {cell.id}: no matching successful execution is available for stale-after={threshold}")
                continue
            started = datetime.fromisoformat(str(record["started_at"]).replace("Z", "+00:00"))
            age = (now - started).total_seconds()
            units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
            limit = float(threshold[:-1]) * units[threshold[-1]]
            if age > limit:
                warnings.append(f"warning: {cell.id}: measurement is stale ({age / 86400:.1f}d old; threshold {threshold})")
        return warnings

    def _run_snapshot(self, document: Document, result: RunResult) -> dict[str, Any]:
        return {
            "document": str(document.path.resolve()) if document.path else None,
            "document_digest": hashlib.sha256(document.source.encode("utf-8")).hexdigest(),
            "cells": {
                cell.id: {
                    "status": cell.status,
                    "stdout": hashlib.sha256(cell.stdout.encode("utf-8")).hexdigest(),
                    "stderr": hashlib.sha256(cell.stderr.encode("utf-8")).hexdigest(),
                    "context": hashlib.sha256(json.dumps(cell.context, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
                    "outputs": {output.name: hashlib.sha256(output.data).hexdigest() for output in cell.outputs},
                }
                for cell in result.cells
            },
        }

    def record_run(self, document: Document, result: RunResult) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        entropy = hashlib.sha256(f"{time.time_ns()}:{os.getpid()}".encode()).hexdigest()[:8]
        run_id = f"{stamp}-{entropy}"
        snapshot = self._run_snapshot(document, result)
        snapshot["run_id"] = run_id
        directory = self.directory / "runs"
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f".{run_id}.tmp"
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(directory / f"{run_id}.json")
        return run_id

    def compare_run(self, document: Document, result: RunResult, previous_run_id: str) -> list[str]:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", previous_run_id):
            raise ValueError("invalid run id")
        try:
            previous = json.loads((self.directory / "runs" / f"{previous_run_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"unknown run id: {previous_run_id}") from error
        document_path = str(document.path.resolve()) if document.path else None
        if previous.get("document") != document_path:
            raise ValueError(f"run id belongs to another document: {previous_run_id}")
        current = self._run_snapshot(document, result)
        before_cells = previous.get("cells", {})
        after_cells = current["cells"]
        changes: list[str] = []
        for cell_id in sorted(set(before_cells) | set(after_cells)):
            if cell_id not in before_cells:
                changes.append(f"{cell_id}: added")
                continue
            if cell_id not in after_cells:
                changes.append(f"{cell_id}: removed")
                continue
            for field in ("status", "stdout", "stderr", "context", "outputs"):
                if before_cells[cell_id].get(field) != after_cells[cell_id].get(field):
                    changes.append(f"{cell_id}: {field} changed")
        return changes


class Runner:
    def __init__(self, cache: Cache | None = None) -> None:
        self.cache = cache or Cache()

    def run(
        self,
        document: Document,
        *,
        cell: str | None = None,
        tag: str | None = None,
        fresh: bool = False,
        tests: bool = False,
        with_tests: bool = False,
        output_dir: str | Path | None = None,
        targets: list[str] | None = None,
        patch: str | None = None,
        context_overrides: dict[str, Any] | None = None,
        event_handler: Callable[[dict[str, Any]], None] | None = None,
    ) -> RunResult:
        errors = [error for error in validate(document) if not error.startswith("warning:")]
        if errors:
            return RunResult(document, [], errors)
        if patch is not None and not cell:
            return RunResult(document, [], ["--patch requires --cell"])
        lookup = document.lookup
        if cell and cell not in lookup:
            return RunResult(document, [], [f"unknown cell: {cell}"])
        if tests and cell and lookup[cell].role != "test":
            return RunResult(document, [], [f"{cell}: pmd test --cell requires a test cell"])
        if not tests and cell and lookup[cell].role not in {"code", "setup"}:
            return RunResult(document, [], [f"{cell}: pmd run --cell requires a code or setup cell"])
        if targets:
            unknown = [target for target in targets if target not in lookup]
            if unknown:
                return RunResult(document, [], [f"unknown cell: {unknown[0]}"])

        roles = {"test"} if tests else {"code", "setup", "test"} if with_tests else {"code", "setup"}
        roots = [candidate for candidate in document.cells if candidate.role in roles and not candidate.skipped]
        if targets is not None:
            roots = [lookup[target] for target in dict.fromkeys(targets)]
        elif cell:
            roots = [lookup[cell]]
        if tag:
            roots = [candidate for candidate in roots if tag in candidate.tags]
        selected = closure([candidate.id for candidate in roots], document) if roots else set()
        ordered = topological_order(selected, document)
        available, _ = engines(document)
        try:
            input_fingerprints = _input_fingerprints(document)
        except OSError as error:
            return RunResult(document, [], [str(error)])
        results: list[CellResult] = []
        produced: dict[str, dict[str, Any]] = {}
        output_directories: dict[str, Path] = {}
        failed: set[str] = set()
        run_root = Path(tempfile.mkdtemp(prefix="pmd-run-"))
        working_directory = document.path.resolve().parent if document.path else Path.cwd()
        root_directory = project_root(document)
        try:
            for candidate in ordered:
                command = available[candidate.language]
                if event_handler:
                    event_handler({"event": "cell_started", "id": candidate.id, "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
                blocking = next((dependency for dependency in candidate.dependencies if dependency in failed), None)
                if candidate.skipped or candidate.role in {"scratch", "lib"}:
                    reason = "cell is skipped" if candidate.skipped else "scratch cells are never executed" if candidate.role == "scratch" else "lib cells are never executed"
                    result = CellResult(candidate.id, "blocked", command, stderr=reason, failure={"cell_id": candidate.id, "language": candidate.language, "kind": "blocked", "message": reason, "exit_code": None, "resolved_context": {}})
                    failed.add(candidate.id)
                    results.append(result)
                    if event_handler:
                        event_handler(_cell_finished_event(candidate, result))
                    continue
                if blocking:
                    reason = f"Blocked by failed dependency: {blocking}"
                    result = CellResult(candidate.id, "blocked", command, stderr=reason, failure={"cell_id": candidate.id, "language": candidate.language, "kind": "dependency_blocked", "message": reason, "dependency": blocking, "exit_code": None, "resolved_context": {}})
                    failed.add(candidate.id)
                    results.append(result)
                    if event_handler:
                        event_handler(_cell_finished_event(candidate, result))
                    continue

                visible: dict[str, Any] = dict(context_overrides or {})
                ancestors = topological_order(closure(candidate.dependencies, document), document) if candidate.dependencies else []
                for ancestor in ancestors:
                    visible.update(produced.get(ancestor.id, {}))
                rendered_document: str | None = None
                if candidate.role == "test" and candidate.attrs.get("test-of") == "document":
                    from .render import render_text

                    rendered_document, _ = render_text(document, RunResult(document, list(results)))
                cell_root = run_root / candidate.id
                cell_output_dir = cell_root / "outputs"
                cell_output_dir.mkdir(parents=True)
                is_patch_target = patch is not None and candidate.id == cell
                execution_cell = replace(candidate, source=patch) if is_patch_target else candidate
                source = source_with_binding(execution_cell, document)
                source_line_offset = source[:max(0, len(source) - len(execution_cell.source))].count("\n")
                if is_patch_target:
                    key = None
                    cached = None
                else:
                    cache_inputs = dict(input_fingerprints)
                    if rendered_document is not None:
                        cache_inputs["__pmd_document_render__"] = hashlib.sha256(rendered_document.encode("utf-8")).hexdigest()
                    key = self.cache.key(candidate, command, visible, source, cache_inputs)
                    is_requested_target = cell == candidate.id or targets is not None and candidate.id in targets
                    cached = None if fresh or is_requested_target else self.cache.load(key, candidate.id, command)
                if cached:
                    _write_outputs(cached.outputs, cell_output_dir)
                    output_directories[candidate.id] = cell_output_dir
                    produced[candidate.id] = cached.context
                    results.append(cached)
                    if output_dir:
                        _write_outputs(cached.outputs, Path(output_dir) / candidate.id)
                    if event_handler:
                        event_handler(_cell_finished_event(candidate, cached))
                    continue

                context_path = cell_root / "context.json"
                context_path.write_text(json.dumps(visible, ensure_ascii=False, sort_keys=True), encoding="utf-8")
                rendered_path = None
                if rendered_document is not None:
                    rendered_path = cell_root / "rendered.txt"
                    rendered_path.write_text(rendered_document, encoding="utf-8")
                timeout = _duration(candidate.attrs.get("timeout", str(document.frontmatter.get("timeout_default", "60s"))))
                started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                started = time.perf_counter()
                try:
                    process = subprocess.run(
                        command, input=source.encode("utf-8"), capture_output=True, cwd=working_directory,
                        env=_cell_environment(
                            candidate,
                            cell_output_dir,
                            context_path,
                            {ancestor.id: output_directories[ancestor.id] for ancestor in ancestors if ancestor.id in output_directories},
                            root_directory,
                            rendered_path,
                        ),
                        timeout=timeout,
                    )
                    stdout = _universal_newlines(process.stdout.decode("utf-8", errors="replace"))
                    stderr = _universal_newlines(process.stderr.decode("utf-8", errors="replace"))
                    final_context = json.loads(context_path.read_text(encoding="utf-8"))
                    delta = {key: value for key, value in final_context.items() if key not in visible or visible[key] != value}
                    expected = int(candidate.attrs.get("expect-exit-code", "0"))
                    status = "passed" if process.returncode == expected else "failed"
                    if status == "passed":
                        schemas, _ = schema_definitions(document)
                        contract_errors: list[str] = []
                        for key, schema_name in produced_contracts(candidate)[0]:
                            if key not in delta:
                                contract_errors.append(f"declared ctx output was not produced: {key}")
                            elif schema_name in schemas:
                                contract_errors.extend(validate_value(delta[key], schemas[schema_name], f"ctx.{key}"))
                        if contract_errors:
                            status = "failed"
                            stderr += "\n".join(f"PMD output contract: {item}" for item in contract_errors) + "\n"
                    result = CellResult(
                        candidate.id, status, command, stdout, stderr, process.returncode,
                        _scan_outputs(cell_output_dir), delta, cache_key=key, started_at=started_at,
                        duration_seconds=time.perf_counter() - started,
                    )
                except subprocess.TimeoutExpired as error:
                    stdout = error.stdout.decode("utf-8", errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
                    stderr = error.stderr.decode("utf-8", errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
                    stdout = _universal_newlines(stdout)
                    stderr = _universal_newlines(stderr)
                    result = CellResult(
                        candidate.id, "failed", command, stdout, stderr + f"Cell timed out after {timeout:g}s",
                        cache_key=key, started_at=started_at, duration_seconds=time.perf_counter() - started,
                    )
                except OSError as error:
                    result = CellResult(
                        candidate.id, "failed", command, stderr=str(error), cache_key=key,
                        started_at=started_at, duration_seconds=time.perf_counter() - started,
                    )
                except (json.JSONDecodeError, OSError) as error:
                    result = CellResult(
                        candidate.id, "failed", command, stderr=f"Invalid PMD context: {error}", cache_key=key,
                        started_at=started_at, duration_seconds=time.perf_counter() - started,
                    )
                if result.status == "failed":
                    result.failure = _structured_failure(candidate, result, visible, source_line_offset)
                results.append(result)
                if event_handler:
                    event_handler(_cell_finished_event(candidate, result))
                output_directories[candidate.id] = cell_output_dir
                if output_dir:
                    _write_outputs(result.outputs, Path(output_dir) / candidate.id)
                if result.status == "passed":
                    produced[candidate.id] = result.context
                    if not is_patch_target:
                        self.cache.store(key, result, document, candidate)
                else:
                    failed.add(candidate.id)
        finally:
            shutil.rmtree(run_root, ignore_errors=True)
        run_result = RunResult(document, results)
        try:
            run_result.run_id = self.cache.record_run(document, run_result)
        except OSError as error:
            run_result.errors.append(f"cannot record run history: {error}")
        return run_result


def _cell_finished_event(cell: Cell, result: CellResult) -> dict[str, Any]:
    return {
        "event": "cell_finished",
        "id": result.id,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": result.status,
        "source_digest": "sha256:" + hashlib.sha256(cell.source.encode("utf-8")).hexdigest(),
        "duration_seconds": result.duration_seconds,
        "stdout": {"bytes": len(result.stdout.encode("utf-8")), "digest": "sha256:" + hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()},
        "stderr": {"bytes": len(result.stderr.encode("utf-8")), "digest": "sha256:" + hashlib.sha256(result.stderr.encode("utf-8")).hexdigest()},
        "outputs": [
            {"name": output.name, "bytes": len(output.data), "digest": "sha256:" + hashlib.sha256(output.data).hexdigest()}
            for output in result.outputs
        ],
        "failure": result.failure,
    }


def _structured_failure(cell: Cell, result: CellResult, visible: dict[str, Any], line_offset: int) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "cell_id": cell.id,
        "language": cell.language,
        "kind": "process_exit",
        "message": result.stderr.strip() or f"process exited with code {result.exit_code}",
        "exit_code": result.exit_code,
        "resolved_context": visible,
    }
    if "timed out after" in result.stderr:
        detail.update(kind="timeout", exception_type="TimeoutExpired")
        return detail
    if "PMD output contract:" in result.stderr:
        detail.update(kind="output_contract", exception_type="OutputContractError")
        return detail
    if result.exit_code is None:
        detail.update(kind="engine_error", exception_type="OSError")
        return detail
    if cell.language not in {"python", "python3"}:
        return detail
    lines = result.stderr.splitlines()
    exception_match = next((
        match for line in reversed(lines)
        if (match := re.match(r"^([A-Za-z_][\w.]*(?:Error|Exception|Interrupt|Exit))(?::\s*(.*))?$", line.strip()))
    ), None)
    traceback_lines = [int(value) for value in re.findall(r'File "<stdin>", line (\d+)', result.stderr)]
    if exception_match:
        detail["exception_type"] = exception_match.group(1)
        detail["message"] = exception_match.group(2) or exception_match.group(1)
    if traceback_lines:
        line_number = max(1, traceback_lines[-1] - line_offset)
        detail["line"] = line_number
        source_lines = cell.source.splitlines()
        if line_number <= len(source_lines):
            detail["source_line"] = source_lines[line_number - 1]
    detail["kind"] = "exception" if exception_match else "process_exit"
    return detail


def execute(document: Document, **kwargs: Any) -> RunResult:
    return Runner().run(document, **kwargs)
