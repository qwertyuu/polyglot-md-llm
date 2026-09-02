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
)
from .graph import graph_lines, validate
from .lint import lint_inputs
from .parser import load
from .render import render_html
from .runner import Runner


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(3, f"{self.prog}: error: {message}\n")


def _parser() -> argparse.ArgumentParser:
    parser = Parser(prog="pmd", description="Execute PMD polyglot Markdown notebooks")
    parser.add_argument("--version", action="version", version="%(prog)s 0.4.1")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    check = commands.add_parser("check", help="validate a document without executing it")
    check.add_argument("file")
    check.add_argument("--graph", action="store_true", help="print the resolved dependency graph")
    check.add_argument("--lint-inputs", action="store_true", help="best-effort static scan for undeclared or stale frontmatter inputs (warnings only)")
    run_commands = {}
    for name in ("run", "test"):
        command = commands.add_parser(name)
        command.add_argument("file")
        command.add_argument("--cell")
        command.add_argument("--tag")
        command.add_argument("--fresh", action="store_true")
        command.add_argument("--verbose", action="store_true", help="print captured stdout and stderr")
        command.add_argument("--out-dir", help="export rich outputs under PATH/<cell-id>/")
        run_commands[name] = command
    run_commands["run"].add_argument(
        "--patch",
        help="execute replacement source (- for stdin, or a file path) against --cell ID's resolved "
             "upstream context; never cached and never written back to the document",
    )
    render = commands.add_parser("render")
    render.add_argument("file")
    render.add_argument("--to", required=True, choices=("html", "pdf", "ipynb"))
    render.add_argument("--out")
    render.add_argument("--fresh", action="store_true")
    render.add_argument("--with-tests", action="store_true", help="execute role=test cells and reflect pass/fail in the render")
    agent = commands.add_parser("agent", help="machine interface for LLM-ready notebooks")
    agent_commands = agent.add_subparsers(dest="agent_command", required=True, parser_class=Parser)
    agent_commands.add_parser("capabilities", help="report protocol capabilities")
    inspect = agent_commands.add_parser("inspect", help="inspect a bounded semantic neighborhood")
    inspect.add_argument("file")
    inspect.add_argument("--request")
    apply = agent_commands.add_parser("apply", help="apply an atomic semantic transaction")
    apply.add_argument("file")
    apply.add_argument("--request", required=True)
    verify = agent_commands.add_parser("verify", help="plan or execute scoped verification")
    verify.add_argument("file")
    verify.add_argument("--request", required=True)
    verify.add_argument("--allow-execution", action="store_true")
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
    try:
        if args.agent_command == "capabilities":
            outcome = capabilities()
        else:
            request = _agent_request(args.request)
            if args.agent_command == "inspect":
                outcome = inspect_document(args.file, request)
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
        return
    if errors:
        print("\n".join(errors), file=sys.stderr)
        raise SystemExit(2)
    if args.command == "render":
        if args.to != "html":
            print(f"render target '{args.to}' is optional and not implemented", file=sys.stderr)
            raise SystemExit(3)
        print("Warning: PMD cells execute with your current user privileges.", file=sys.stderr)
        output, result = render_html(document, fresh=args.fresh, with_tests=args.with_tests)
        destination = Path(args.out) if args.out else Path(args.file).with_suffix(".html")
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
    result = Runner().run(
        document,
        cell=args.cell,
        tag=args.tag,
        fresh=args.fresh,
        tests=args.command == "test",
        output_dir=args.out_dir,
        patch=patch_source,
    )
    _print_results(result, tests=args.command == "test", verbose=args.verbose)
    raise SystemExit(0 if result.ok else 1)


if __name__ == "__main__":
    main()

