from __future__ import annotations

import base64
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT / "src"))

from pmd_notebook import Runner, parse, validate  # noqa: E402


def result_json(result) -> dict[str, object]:
    cells = []
    for cell in result.cells:
        outputs = []
        for output in cell.outputs:
            suffix = Path(output.name).suffix.lower().lstrip(".")
            data = output.data.decode("utf-8", errors="replace") if output.kind in {"markdown", "csv"} else base64.b64encode(output.data).decode("ascii")
            outputs.append({"name": output.name, "kind": suffix, "data": data})
        cells.append({
            "id": cell.id, "status": cell.status, "stdout": cell.stdout,
            "stderr": cell.stderr, "outputs": outputs,
        })
    return {"ok": result.ok, "errors": result.errors, "cells": cells}


class App(SimpleHTTPRequestHandler):
    def document_path(self, requested: str) -> Path:
        path = (ROOT / requested).resolve()
        if ROOT not in path.parents or path.suffix != ".pmd":
            raise ValueError("Only .pmd files inside the PMD workspace may be accessed")
        return path

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/files":
            return self.reply({"files": [str(path.relative_to(ROOT)) for path in ROOT.rglob("*.pmd")]})
        if parsed.path == "/api/document":
            try:
                path = self.document_path(query.get("path", ["example.pmd"])[0])
                return self.reply({"path": str(path.relative_to(ROOT)), "source": path.read_text(encoding="utf-8")})
            except (ValueError, OSError) as error:
                return self.reply({"ok": False, "error": str(error)}, 400)
        return super().do_GET()

    def do_POST(self) -> None:
        if self.path not in {"/api/run", "/api/check", "/api/save"}:
            self.send_error(404)
            return
        size = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(size))
        if self.path == "/api/save":
            try:
                path = self.document_path(data["path"])
                path.write_text(data["source"], encoding="utf-8")
                return self.reply({"ok": True, "path": str(path.relative_to(ROOT))})
            except (KeyError, ValueError, OSError) as error:
                return self.reply({"ok": False, "error": str(error)}, 400)
        document = parse(data["source"], ROOT / data.get("path", "untitled.pmd"))
        if self.path == "/api/check":
            errors = validate(document)
            return self.reply({"ok": not [item for item in errors if not item.startswith("warning:")], "errors": errors})
        return self.reply(result_json(Runner().run(document, cell=data.get("cell"), tests=data.get("tests", False))))

    def reply(self, data: object, code: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    os.chdir(ROOT)
    print("PMD workbench: http://localhost:8765")
    ThreadingHTTPServer(("", 8765), App).serve_forever()

