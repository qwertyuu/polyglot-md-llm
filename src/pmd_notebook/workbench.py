from __future__ import annotations

import base64
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name

from .graph import validate
from .parser import parse
from .runner import Runner


def result_json(result) -> dict[str, object]:
    cells = []
    for cell in result.cells:
        outputs = []
        for output in cell.outputs:
            suffix = Path(output.name).suffix.lower().lstrip(".")
            data = output.data.decode("utf-8", errors="replace") if output.kind in {"markdown", "csv"} else base64.b64encode(output.data).decode("ascii")
            outputs.append({"name": output.name, "kind": suffix, "data": data})
        cells.append({"id": cell.id, "status": cell.status, "stdout": cell.stdout, "stderr": cell.stderr, "outputs": outputs})
    return {"ok": result.ok, "errors": result.errors, "cells": cells}


def application(workspace: Path):
    root = workspace.resolve()
    assets = files("pmd_notebook").joinpath("workbench")

    class App(SimpleHTTPRequestHandler):
        def document_path(self, requested: str) -> Path:
            path = (root / requested).resolve()
            if root not in path.parents or path.suffix != ".pmd":
                raise ValueError("Only .pmd files inside the selected workspace may be accessed")
            return path

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/api/files":
                return self.reply({"files": [str(path.relative_to(root)) for path in root.rglob("*.pmd")]})
            if parsed.path == "/api/document":
                try:
                    path = self.document_path(query.get("path", [""])[0])
                    return self.reply({"path": str(path.relative_to(root)), "source": path.read_text(encoding="utf-8")})
                except (ValueError, OSError) as error:
                    return self.reply({"ok": False, "error": str(error)}, 400)
            if parsed.path == "/highlight.css":
                body = HtmlFormatter(style="friendly").get_style_defs(".highlight").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/css; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            names = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            name = names.get(parsed.path)
            if name:
                content_type = "text/html; charset=utf-8" if name.endswith("html") else "text/css; charset=utf-8" if name.endswith("css") else "application/javascript; charset=utf-8"
                body = assets.joinpath(name).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(404)

        def do_POST(self) -> None:
            if self.path not in {"/api/run", "/api/check", "/api/save", "/api/highlight"}:
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", 0))
                if size > 10_000_000:
                    raise ValueError("request body exceeds 10 MB")
                data = json.loads(self.rfile.read(size))
            except (ValueError, json.JSONDecodeError) as error:
                return self.reply({"ok": False, "error": str(error)}, 400)
            if self.path == "/api/highlight":
                source = data.get("source")
                language = data.get("language")
                if not isinstance(source, str) or not isinstance(language, str):
                    return self.reply({"ok": False, "error": "source and language must be strings"}, 400)
                try:
                    lexer = get_lexer_by_name(language)
                except Exception:
                    lexer = TextLexer()
                return self.reply({"ok": True, "html": pygments_highlight(source, lexer, HtmlFormatter(nowrap=True, style="friendly"))})
            if self.path == "/api/save":
                try:
                    path = self.document_path(data["path"])
                    path.write_text(data["source"], encoding="utf-8")
                    return self.reply({"ok": True, "path": str(path.relative_to(root))})
                except (KeyError, TypeError, ValueError, OSError) as error:
                    return self.reply({"ok": False, "error": str(error)}, 400)
            try:
                document = parse(data["source"], root / data.get("path", "untitled.pmd"))
            except (KeyError, TypeError, ValueError) as error:
                return self.reply({"ok": False, "error": str(error)}, 400)
            if self.path == "/api/check":
                errors = validate(document)
                return self.reply({"ok": not [item for item in errors if not item.startswith("warning:")], "errors": errors})
            return self.reply(result_json(Runner().run(document, cell=data.get("cell"), tests=data.get("tests", False))))

        def reply(self, data: object, code: int = 200) -> None:
            body = json.dumps(data).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return App


def serve(workspace: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    if not workspace.is_dir():
        raise SystemExit(f"workbench workspace is not a directory: {workspace}")
    print(f"PMD workbench: http://{host}:{port}")
    ThreadingHTTPServer((host, port), application(workspace)).serve_forever()
