from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bindings import source_with_binding
from .graph import closure, engines, topological_order, validate
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
    dependency_outputs: dict[str, Path],
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({
        "PMD_CELL_OUT": str(output),
        "PMD_CTX_FILE": str(context),
        "PMD_DEP_OUTPUTS": json.dumps({key: str(value) for key, value in dependency_outputs.items()}),
        "PYTHONUTF8": "1",
    })
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
    document_dir = document.path.resolve().parent if document.path else Path.cwd()
    paths: list[Path] = []
    for value in values:
        expanded = os.path.expandvars(value).replace("{document_dir}", str(document_dir))
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
            )
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return None

    def store(self, key: str, result: CellResult) -> None:
        if result.status != "passed":
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        data = {
            "stdout": result.stdout, "stderr": result.stderr, "exit_code": result.exit_code, "context": result.context,
            "outputs": [{"name": item.name, "kind": item.kind, "data": base64.b64encode(item.data).decode("ascii")} for item in result.outputs],
        }
        temporary = self.directory / f".{key}.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(self.directory / f"{key}.json")


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
        try:
            for candidate in ordered:
                command = available[candidate.language]
                blocking = next((dependency for dependency in candidate.dependencies if dependency in failed), None)
                if candidate.skipped or candidate.role in {"scratch", "lib"}:
                    reason = "cell is skipped" if candidate.skipped else "scratch cells are never executed" if candidate.role == "scratch" else "lib cells are never executed"
                    result = CellResult(candidate.id, "blocked", command, stderr=reason)
                    failed.add(candidate.id)
                    results.append(result)
                    continue
                if blocking:
                    result = CellResult(candidate.id, "blocked", command, stderr=f"Blocked by failed dependency: {blocking}")
                    failed.add(candidate.id)
                    results.append(result)
                    continue

                visible: dict[str, Any] = {}
                ancestors = topological_order(closure(candidate.dependencies, document), document) if candidate.dependencies else []
                for ancestor in ancestors:
                    visible.update(produced.get(ancestor.id, {}))
                cell_root = run_root / candidate.id
                cell_output_dir = cell_root / "outputs"
                cell_output_dir.mkdir(parents=True)
                is_patch_target = patch is not None and candidate.id == cell
                execution_cell = replace(candidate, source=patch) if is_patch_target else candidate
                source = source_with_binding(execution_cell, document)
                if is_patch_target:
                    key = None
                    cached = None
                else:
                    key = self.cache.key(candidate, command, visible, source, input_fingerprints)
                    is_requested_target = cell == candidate.id or targets is not None and candidate.id in targets
                    cached = None if fresh or is_requested_target else self.cache.load(key, candidate.id, command)
                if cached:
                    _write_outputs(cached.outputs, cell_output_dir)
                    output_directories[candidate.id] = cell_output_dir
                    produced[candidate.id] = cached.context
                    results.append(cached)
                    if output_dir:
                        _write_outputs(cached.outputs, Path(output_dir) / candidate.id)
                    continue

                context_path = cell_root / "context.json"
                context_path.write_text(json.dumps(visible, ensure_ascii=False, sort_keys=True), encoding="utf-8")
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
                        ),
                        timeout=timeout,
                    )
                    stdout = _universal_newlines(process.stdout.decode("utf-8", errors="replace"))
                    stderr = _universal_newlines(process.stderr.decode("utf-8", errors="replace"))
                    final_context = json.loads(context_path.read_text(encoding="utf-8"))
                    delta = {key: value for key, value in final_context.items() if key not in visible or visible[key] != value}
                    expected = int(candidate.attrs.get("expect-exit-code", "0"))
                    status = "passed" if process.returncode == expected else "failed"
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
                results.append(result)
                output_directories[candidate.id] = cell_output_dir
                if output_dir:
                    _write_outputs(result.outputs, Path(output_dir) / candidate.id)
                if result.status == "passed":
                    produced[candidate.id] = result.context
                    if not is_patch_target:
                        self.cache.store(key, result)
                else:
                    failed.add(candidate.id)
        finally:
            shutil.rmtree(run_root, ignore_errors=True)
        return RunResult(document, results)


def execute(document: Document, **kwargs: Any) -> RunResult:
    return Runner().run(document, **kwargs)

