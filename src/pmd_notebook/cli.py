from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .agent_protocol import (
    DEFAULT_MAX_RESPONSE,
    ProtocolError,
    apply_transaction,
    capabilities,
    error_result,
    inspect_document,
    verify_document,
    digest,
    read_source,
)
from .graph import graph_lines, validate
from .lint import lint_inputs
from .lint import strict_input_findings
from .editing import audit_dependencies, extract_cell, format_document, inline_file
from .contracts import produced_contracts
from .attestation import provenance_statement
from .parser import load
from .render import render_html, render_text
from .runner import Runner


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(3, f"{self.prog}: error: {message}\n")


def _default_project_python(platform: str | None = None) -> str:
    platform = platform or sys.platform
    executable = ".venv/Scripts/python.exe" if platform == "win32" else ".venv/bin/python"
    return f"{{project_dir}}/{executable}"


def _parser() -> argparse.ArgumentParser:
    parser = Parser(prog="pmd", description="Execute PMD polyglot Markdown notebooks")
    parser.add_argument("--version", action="version", version="%(prog)s 0.6.0")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    check = commands.add_parser("check", help="validate a document without executing it")
    check.add_argument("file")
    check.add_argument("--graph", action="store_true", help="print the resolved dependency graph")
    check.add_argument("--lint-inputs", action="store_true", help="best-effort static scan for undeclared or stale frontmatter inputs (warnings only)")
    check.add_argument("--strict-inputs", action="store_true", help="CI mode: fail on high-confidence undeclared literal inputs")
    run_commands = {}
    for name in ("run", "test"):
        command = commands.add_parser(name)
        command.add_argument("file")
        command.add_argument("--cell")
        command.add_argument("--tag")
        command.add_argument("--fresh", action="store_true")
        command.add_argument("--verbose", action="store_true", help="print captured stdout and stderr")
        command.add_argument("--out-dir", help="export rich outputs under PATH/<cell-id>/")
        command.add_argument("--set", dest="set_values", action="append", default=[], metavar="PATH=JSON", help="override run-scoped context (repeatable)")
        run_commands[name] = command
    run_commands["run"].add_argument(
        "--patch",
        help="execute replacement source (- for stdin, or a file path) against --cell ID's resolved "
             "upstream context; never cached and never written back to the document",
    )
    run_commands["run"].add_argument("--sweep", action="append", default=[], metavar="PATH=JSON,...", help="run one isolated variant per value (one axis)")
    run_commands["run"].add_argument("--compare-with", metavar="RUN_ID", help="report observable output changes since a previous run")
    render = commands.add_parser("render")
    render.add_argument("file")
    render.add_argument("--to", required=True, choices=("html", "text", "pdf", "ipynb"))
    render.add_argument("--out")
    render.add_argument("--fresh", action="store_true")
    render.add_argument("--with-tests", action="store_true", help="execute role=test cells and reflect pass/fail in the render")
    render.add_argument("--hide-graph", action="store_true", help="omit the cell graph from HTML output")
    render.add_argument("--hide-source", action="store_true", help="omit cell source disclosures from HTML output")
    call = commands.add_parser("call", help="invoke a notebook through its typed output contract")
    call.add_argument("file")
    call.add_argument("--input", default="{}", help="JSON object, - for stdin, or @PATH")
    call.add_argument("--output", action="append", required=True, help="declared ctx output key (repeatable)")
    call.add_argument("--fresh", action="store_true")
    attest = commands.add_parser("attest", help="emit an unsigned in-toto/SLSA statement from a verified receipt")
    attest.add_argument("file")
    attest.add_argument("--receipt", required=True)
    attest.add_argument("--out")
    workbench = commands.add_parser("workbench", help="start the local browser workbench")
    workbench.add_argument("workspace", nargs="?", default=".", help="directory containing .pmd files (default: current directory)")
    workbench.add_argument("--host", default="127.0.0.1", help="bind address (default: loopback only)")
    workbench.add_argument("--port", type=int, default=8765, help="listening port (default: 8765)")
    init = commands.add_parser("init", help="create pmd.yaml and a minimal notebook")
    init.add_argument("directory", nargs="?", default=".")
    init.add_argument("--force", action="store_true")
    fmt = commands.add_parser("fmt", help="normalize PMD frontmatter and fence attributes")
    fmt.add_argument("file")
    extract = commands.add_parser("extract", help="write one cell's source to a normal module")
    extract.add_argument("file")
    extract.add_argument("cell")
    extract.add_argument("--out")
    inline = commands.add_parser("inline", help="print a source module as a PMD cell")
    inline.add_argument("file")
    inline.add_argument("--cell")
    audit = commands.add_parser("audit-deps", help="suggest local source-module inputs")
    audit.add_argument("file")
    agent = commands.add_parser("agent", help="machine interface for LLM-ready notebooks")
    agent_commands = agent.add_subparsers(dest="agent_command", required=True, parser_class=Parser)
    agent_commands.add_parser("capabilities", help="report protocol capabilities")
    inspect = agent_commands.add_parser("inspect", help="inspect a bounded semantic neighborhood")
    inspect.add_argument("file")
    inspect.add_argument("--request")
    inspect.add_argument("--include-rendered", action="store_true", help="include reader-visible cell output (requires --allow-execution)")
    inspect.add_argument("--allow-execution", action="store_true")
    apply = agent_commands.add_parser("apply", help="apply an atomic semantic transaction")
    apply.add_argument("file")
    apply.add_argument("--request", required=True)
    verify = agent_commands.add_parser("verify", help="plan or execute scoped verification")
    verify.add_argument("file")
    verify.add_argument("--request", required=True)
    verify.add_argument("--allow-execution", action="store_true")
    edit = agent_commands.add_parser("edit", help="replace a cell from a source file with digest preconditions")
    edit.add_argument("file")
    edit.add_argument("--cell", required=True)
    edit.add_argument("--from", dest="source_file", required=True)
    agent_run = agent_commands.add_parser("run", help="execute with an NDJSON event stream")
    agent_run.add_argument("file")
    agent_run.add_argument("--stream", action="store_true", required=True)
    agent_run.add_argument("--fresh", action="store_true")
    agent_run.add_argument("--allow-execution", action="store_true")
    return parser


def _agent_request(location: str | None) -> dict:
    if location is None:
        return {}
    try:
        raw = sys.stdin.read() if location == "-" else Path(location).read_text(encoding="utf-8")
    except OSError as error:
        raise ProtocolError("invalid_request", f"cannot read request: {error}") from error
    if len(raw.encode("utf-8")) > DEFAULT_MAX_RESPONSE:
        raise ProtocolError("invalid_request", "request exceeds max_request_bytes")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProtocolError("invalid_request", f"invalid request JSON: {error}") from error
    if not isinstance(value, dict):
        raise ProtocolError("invalid_request", "request JSON must be an object")
    return value


def _run_agent(args: argparse.Namespace) -> None:
    if args.agent_command == "run":
        if not args.allow_execution:
            print(json.dumps({"event": "run_blocked", "code": "authorization_required", "message": "host execution authorization is required"}, separators=(",", ":")))
            raise SystemExit(5)
        try:
            document = load(args.file)
        except (OSError, UnicodeError) as error:
            print(json.dumps({"event": "run_failed", "code": "document_invalid", "message": str(error)}, ensure_ascii=False, separators=(",", ":")))
            raise SystemExit(2) from error
        errors = [item for item in validate(document) if not item.startswith("warning:")]
        if errors:
            print(json.dumps({"event": "run_failed", "code": "document_invalid", "errors": errors}, ensure_ascii=False, separators=(",", ":")))
            raise SystemExit(2)
        emit = lambda event: print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)
        emit({"event": "run_started", "document_revision": read_source(args.file).revision})
        result = Runner().run(document, fresh=args.fresh, event_handler=emit)
        emit({"event": "run_finished", "status": "passed" if result.ok else "failed", "run_id": result.run_id})
        raise SystemExit(0 if result.ok else 1)
    try:
        if args.agent_command == "capabilities":
            outcome = capabilities()
        elif args.agent_command == "edit":
            source = read_source(args.file)
            document = load(args.file)
            cell = document.lookup.get(args.cell)
            if cell is None:
                raise ProtocolError("unknown_cell", f"unknown cell: {args.cell}")
            replacement = Path(args.source_file).read_text(encoding="utf-8").rstrip("\r\n")
            outcome = apply_transaction(args.file, {
                "base_revision": source.revision,
                "operations": [{"op": "replace_cell_source", "cell_id": cell.id,
                                "expected_source_digest": digest(cell.source), "source": replacement}],
            })
        else:
            request = _agent_request(args.request)
            if args.agent_command == "inspect":
                if args.include_rendered:
                    request["include_rendered"] = True
                outcome = inspect_document(args.file, request, allow_execution=args.allow_execution)
            elif args.agent_command == "apply":
                outcome = apply_transaction(args.file, request)
            else:
                outcome = verify_document(args.file, request, allow_execution=args.allow_execution)
    except ProtocolError as error:
        outcome = error_result(args.agent_command, error)
    print(json.dumps(outcome.response, ensure_ascii=False, separators=(",", ":")))
    raise SystemExit(outcome.exit_code)


def _print_results(result, tests: bool = False, verbose: bool = False) -> None:
    for cell in result.cells:
        is_test = result.document.lookup[cell.id].role == "test"
        label = "PASS" if tests and is_test and cell.status in {"passed", "cached"} else "FAIL" if tests and is_test else cell.status.upper()
        suffix = " (cached)" if cell.cached else ""
        print(f"{label:7} {cell.id}{suffix}")
        if verbose and cell.stdout:
            print(f"--- {cell.id} stdout ---")
            print(cell.stdout, end="" if cell.stdout.endswith("\n") else "\n")
        if verbose and cell.stderr and cell.status != "failed":
            print(f"--- {cell.id} stderr ---", file=sys.stderr)
            print(cell.stderr, file=sys.stderr, end="" if cell.stderr.endswith("\n") else "\n")
        if cell.status == "failed":
            command = subprocess_command(cell.command)
            print(f"command: {command}", file=sys.stderr)
            if cell.stderr:
                print(cell.stderr, file=sys.stderr, end="" if cell.stderr.endswith("\n") else "\n")
    for error in result.errors:
        print(error, file=sys.stderr)


def subprocess_command(command: list[str]) -> str:
    return shlex.join(command)


def _json_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _context_assignments(values: list[str]) -> dict:
    result: dict = {}
    for assignment in values:
        if "=" not in assignment:
            raise ValueError(f"context override must use PATH=JSON: {assignment}")
        path, raw = assignment.split("=", 1)
        keys = path.split(".")
        if not all(keys):
            raise ValueError(f"context override path is invalid: {path}")
        target = result
        for key in keys[:-1]:
            existing = target.get(key)
            if existing is None:
                existing = {}
                target[key] = existing
            if not isinstance(existing, dict):
                raise ValueError(f"context override path conflicts at: {key}")
            target = existing
        target[keys[-1]] = _json_value(raw)
    return result


def _merge_context(base: dict, overlay: dict) -> dict:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_context(merged[key], value)
        else:
            merged[key] = value
    return merged


def _ensure_utf8_streams(streams: tuple | None = None) -> None:
    for stream in streams if streams is not None else (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> None:
    _ensure_utf8_streams()
    args = _parser().parse_args(argv)
    if args.command == "agent":
        _run_agent(args)
    if args.command == "workbench":
        from .workbench import serve

        serve(Path(args.workspace), args.host, args.port)
        return
    if args.command == "init":
        directory = Path(args.directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        config = directory / "pmd.yaml"
        notebook = directory / "notebook.pmd"
        if not args.force and (config.exists() or notebook.exists()):
            print("pmd init refuses to overwrite existing pmd.yaml or notebook.pmd; use --force", file=sys.stderr)
            raise SystemExit(3)
        project_python = _default_project_python()
        config.write_text(
            "# Project-level interpreter configuration.\n"
            "engines:\n"
            "  python:\n"
            f"    command: \"{project_python}\"\n",
            encoding="utf-8",
        )
        notebook.write_text("---\ntitle: Untitled PMD notebook\n---\n\n# Untitled PMD notebook\n\n```python\nprint(\"Hello from an isolated PMD cell\")\n```\n", encoding="utf-8")
        print(config)
        print(notebook)
        return
    if args.command == "fmt":
        path = Path(args.file)
        path.write_text(format_document(path), encoding="utf-8")
        print(path)
        return
    if args.command == "extract":
        try:
            print(extract_cell(args.file, args.cell, args.out))
        except ValueError as error:
            print(error, file=sys.stderr)
            raise SystemExit(3)
        return
    if args.command == "inline":
        print(inline_file(args.file, args.cell), end="")
        return
    if args.command == "audit-deps":
        paths = audit_dependencies(args.file)
        if paths:
            print("Suggested frontmatter inputs:")
            print("inputs:\n" + "\n".join(f"  - {path}" for path in paths))
        else:
            print("No local source-module imports found.")
        return
    if args.command == "attest":
        try:
            receipt_value = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
            receipt = receipt_value.get("result", {}).get("receipt", receipt_value)
            source = read_source(args.file)
            if not isinstance(receipt, dict) or receipt.get("status") != "verified":
                raise ValueError("attestation requires a verified receipt")
            if receipt.get("document_revision") != source.revision:
                raise ValueError("receipt does not match the current document revision")
            statement = provenance_statement(Path(args.file), receipt)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(error, file=sys.stderr)
            raise SystemExit(3) from error
        serialized = json.dumps(statement, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if args.out:
            Path(args.out).write_text(serialized + "\n", encoding="utf-8")
            print(args.out)
        else:
            print(serialized)
        return
    try:
        document = load(args.file)
    except (OSError, UnicodeError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(3) from error
    diagnostics = validate(document)
    warnings = [item for item in diagnostics if item.startswith("warning:")]
    errors = [item for item in diagnostics if not item.startswith("warning:")]
    for warning in warnings:
        print(warning, file=sys.stderr)
    if args.command == "check":
        if errors:
            print("\n".join(errors), file=sys.stderr)
            raise SystemExit(2)
        print("PMD document is valid")
        if args.graph:
            print("\n".join(graph_lines(document)))
        if args.lint_inputs:
            for message in lint_inputs(document):
                print(f"lint: {message}", file=sys.stderr)
        if args.strict_inputs:
            high, low = strict_input_findings(document)
            for message in low:
                print(f"lint advisory: {message}", file=sys.stderr)
            if high:
                for message in high:
                    print(f"strict input error: {message}", file=sys.stderr)
                raise SystemExit(2)
        for message in Runner().cache.stale_warnings(document):
            print(message, file=sys.stderr)
        return
    if errors:
        print("\n".join(errors), file=sys.stderr)
        raise SystemExit(2)
    if args.command == "call":
        try:
            if args.input == "-":
                raw_input = sys.stdin.read()
            elif args.input.startswith("@"):
                raw_input = Path(args.input[1:]).read_text(encoding="utf-8")
            else:
                raw_input = args.input
            input_value = json.loads(raw_input)
        except (OSError, json.JSONDecodeError) as error:
            print(f"invalid call input: {error}", file=sys.stderr)
            raise SystemExit(3) from error
        if not isinstance(input_value, dict):
            print("call input must be a JSON object", file=sys.stderr)
            raise SystemExit(3)
        declared = {
            key
            for cell in document.cells
            for key, _ in produced_contracts(cell)[0]
        }
        unknown = [key for key in args.output if key not in declared]
        if unknown:
            print(f"output is not declared by a produces contract: {unknown[0]}", file=sys.stderr)
            raise SystemExit(3)
        print("Warning: PMD cells execute with your current user privileges.", file=sys.stderr)
        result = Runner().run(document, fresh=args.fresh, context_overrides=input_value)
        if not result.ok:
            _print_results(result)
            raise SystemExit(1)
        context: dict = {}
        for cell in result.cells:
            context.update(cell.context)
        missing = [key for key in args.output if key not in context]
        if missing:
            print(f"declared output was not produced: {missing[0]}", file=sys.stderr)
            raise SystemExit(1)
        value = context[args.output[0]] if len(args.output) == 1 else {key: context[key] for key in args.output}
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        return
    if args.command == "render":
        if args.to not in {"html", "text"}:
            print(f"render target '{args.to}' is optional and not implemented", file=sys.stderr)
            raise SystemExit(3)
        print("Warning: PMD cells execute with your current user privileges.", file=sys.stderr)
        renderer = render_html if args.to == "html" else render_text
        render_options = {"fresh": args.fresh, "with_tests": args.with_tests}
        if args.to == "html":
            render_options.update(show_graph=not args.hide_graph, show_source=not args.hide_source)
        output, result = renderer(document, **render_options)
        suffix = ".html" if args.to == "html" else ".txt"
        destination = Path(args.out) if args.out else Path(args.file).with_suffix(suffix)
        destination.write_text(output, encoding="utf-8")
        _print_results(result)
        print(destination)
        raise SystemExit(0 if result.ok else 1)
    patch_source = None
    patch_location = getattr(args, "patch", None)
    if patch_location is not None:
        if not args.cell:
            print("pmd run --patch requires --cell ID", file=sys.stderr)
            raise SystemExit(3)
        try:
            patch_source = sys.stdin.read() if patch_location == "-" else Path(patch_location).read_text(encoding="utf-8")
        except OSError as error:
            print(error, file=sys.stderr)
            raise SystemExit(3) from error
    print("Warning: PMD cells execute with your current user privileges.", file=sys.stderr)
    try:
        context_overrides = _context_assignments(args.set_values)
    except ValueError as error:
        print(error, file=sys.stderr)
        raise SystemExit(3) from error
    sweep_values = getattr(args, "sweep", [])
    if sweep_values:
        if len(sweep_values) != 1 or "=" not in sweep_values[0]:
            print("--sweep currently accepts exactly one PATH=JSON,... axis", file=sys.stderr)
            raise SystemExit(3)
        sweep_path, raw_values = sweep_values[0].split("=", 1)
        variants = raw_values.split(",")
        if not variants or any(value == "" for value in variants):
            print("--sweep requires at least one non-empty value", file=sys.stderr)
            raise SystemExit(3)
        outcomes = []
        for raw in variants:
            variant = _context_assignments([f"{sweep_path}={raw}"])
            print(f"=== {sweep_path}={raw} ===")
            outcome = Runner().run(
                document, cell=args.cell, tag=args.tag, fresh=args.fresh,
                output_dir=args.out_dir, patch=patch_source,
                context_overrides=_merge_context(context_overrides, variant),
            )
            _print_results(outcome, verbose=args.verbose)
            if outcome.run_id:
                print(f"Run ID: {outcome.run_id}")
            outcomes.append(outcome)
        raise SystemExit(0 if all(outcome.ok for outcome in outcomes) else 1)
    result = Runner().run(
        document,
        cell=args.cell,
        tag=args.tag,
        fresh=args.fresh,
        tests=args.command == "test",
        output_dir=args.out_dir,
        patch=patch_source,
        context_overrides=context_overrides,
    )
    _print_results(result, tests=args.command == "test", verbose=args.verbose)
    if result.run_id:
        print(f"Run ID: {result.run_id}")
    compare_with = getattr(args, "compare_with", None)
    if compare_with:
        try:
            changes = Runner().cache.compare_run(document, result, compare_with)
        except ValueError as error:
            print(error, file=sys.stderr)
            raise SystemExit(3) from error
        if changes:
            print("Changes since " + compare_with + ":")
            print("\n".join(changes))
        else:
            print(f"No output changes since {compare_with}")
    raise SystemExit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
