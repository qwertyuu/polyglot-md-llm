from __future__ import annotations

import base64
import csv
import html
import io
from pathlib import Path

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

from .models import Cell, CellResult, Document, RichOutput, RunResult
from .runner import Runner

MARKDOWN = MarkdownIt("commonmark", {"html": False, "linkify": False})
SOURCE_FORMATTER = HtmlFormatter(nowrap=True, style="friendly")
SOURCE_STYLE = SOURCE_FORMATTER.get_style_defs(".source .highlight")

STYLE = """
:root{--ink:#18221d;--muted:#657168;--paper:#f4f0e6;--card:#fffdf7;--rule:#c9c1af;--accent:#b94b2f;--code:#15231d;--code-ink:#e8f1e9}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#eee7d8 0,#f8f5ed 45%,#e8eee7 100%);color:var(--ink);font:17px/1.62 Georgia,"Times New Roman",serif}
main{width:min(940px,calc(100% - 32px));margin:56px auto 96px}h1,h2,h3{line-height:1.12;letter-spacing:-.025em}h1{font-size:clamp(2.5rem,8vw,5.5rem);margin:.2em 0 .35em}a{color:#80402d}code,pre,.cell-head,summary{font-family:"Cascadia Mono","SFMono-Regular",Consolas,monospace}
code{background:#e5e1d7;padding:.1em .3em}pre{white-space:pre-wrap;word-break:break-word}.cell{margin:34px 0;border:1px solid var(--rule);background:var(--card);box-shadow:8px 8px 0 #d8d0bf}
.cell-head{display:flex;justify-content:space-between;gap:16px;padding:10px 14px;background:#e8e3d7;color:#49544d;font-size:.78rem;text-transform:uppercase;letter-spacing:.08em}.status-failed{color:#a12d1d}.status-passed,.status-cached{color:#29603c}
details{border-top:1px solid var(--rule)}summary{cursor:pointer;padding:10px 14px;font-size:.78rem;color:var(--muted)}summary:hover{color:var(--ink);background:#f2eee4}.source,.stream{margin:0;padding:16px;overflow:auto;font-size:.84rem}.source{max-height:24rem;background:#f6f3eb;color:#26342b;border-left:4px solid #9eaa91;white-space:pre}.source code{padding:0;background:transparent}.result{padding:16px;background:var(--code);color:var(--code-ink);border-top:1px solid var(--rule)}.result-label{display:block;margin-bottom:8px;color:#b9cbbd;font:700 .7rem "Cascadia Mono","SFMono-Regular",Consolas,monospace;letter-spacing:.1em;text-transform:uppercase}.result pre{margin:0;font:inherit}.stream{background:#f6f3eb;color:#3d4941}.error{padding:16px;background:#fff0eb;color:#8b2519;border-top:1px solid #e6b7aa}.error strong{display:block;margin-bottom:6px}.error pre{margin:0;font:inherit;white-space:pre-wrap}.output{padding:16px;border-top:1px solid var(--rule);overflow:auto}.output img{display:block;max-width:100%;height:auto}.output table{border-collapse:collapse;width:100%;font-size:.9rem}.output th,.output td{border:1px solid var(--rule);padding:6px 9px;text-align:left}.attachment{display:inline-block;padding:8px 12px;border:1px solid currentColor}
.warning{padding:12px 16px;border-left:4px solid var(--accent);background:#fff5e7}@media(max-width:600px){main{margin-top:24px}.cell{box-shadow:4px 4px 0 #d8d0bf}.cell-head{align-items:flex-start;flex-direction:column}}
"""


def _image_mime(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}[suffix]


def _rich_output(output: RichOutput) -> str:
    name = html.escape(output.name)
    if output.kind == "image":
        encoded = base64.b64encode(output.data).decode("ascii")
        return f'<div class="output"><img alt="{name}" src="data:{_image_mime(output.name)};base64,{encoded}"></div>'
    if output.kind == "markdown":
        return f'<div class="output">{MARKDOWN.render(output.data.decode("utf-8", errors="replace"))}</div>'
    if output.kind == "csv":
        rows = csv.reader(io.StringIO(output.data.decode("utf-8", errors="replace")))
        rendered = []
        for index, row in enumerate(rows):
            tag = "th" if index == 0 else "td"
            rendered.append("<tr>" + "".join(f"<{tag}>{html.escape(value)}</{tag}>" for value in row) + "</tr>")
        return f'<div class="output"><table>{"".join(rendered)}</table></div>'
    encoded = base64.b64encode(output.data).decode("ascii")
    return f'<div class="output"><a class="attachment" download="{name}" href="data:application/octet-stream;base64,{encoded}">Download {name}</a></div>'


def _highlight_source(source: str, language: str) -> str:
    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        lexer = TextLexer()
    return highlight(source, lexer, SOURCE_FORMATTER)


def _cell_html(cell: Cell, result: CellResult | None, document: Document) -> str:
    status = result.status if result else "not-run"
    parts = [
        '<section class="cell">',
        f'<header class="cell-head"><strong>{html.escape(cell.id)}</strong><span>{html.escape(cell.language)} / <span class="status-{status}">{status}</span></span></header>',
    ]
    if cell.role == "lib":
        users = sorted(candidate.id for candidate in document.cells if cell.id in candidate.uses)
        note = "Not executed - composed into: " + (", ".join(users) if users else "(not used by any cell)")
        parts.append(f'<div class="warning">{html.escape(note)}</div>')
    elif cell.uses:
        parts.append(f'<div class="warning">{html.escape("uses (composed source): " + ", ".join(cell.uses))}</div>')
    if result:
        if result.stdout:
            parts.append(
                f'<div class="result"><span class="result-label">Result</span><pre>{html.escape(result.stdout)}</pre></div>'
            )
        if result.status in {"failed", "blocked"}:
            message = result.stderr or "This step did not complete."
            parts.append(f'<div class="error"><strong>Could not complete this step</strong><pre>{html.escape(message)}</pre></div>')
        parts.extend(_rich_output(output) for output in result.outputs)
        if result.stderr and result.status not in {"failed", "blocked"}:
            parts.append(f'<details><summary>Technical details</summary><pre class="stream">{html.escape(result.stderr)}</pre></details>')
    parts.append(
        f'<details><summary>View source</summary><pre class="source"><code class="highlight">{_highlight_source(cell.source, cell.language)}</code></pre></details>'
    )
    parts.append("</section>")
    return "".join(parts)


def render_html(document: Document, result: RunResult | None = None, *, fresh: bool = False, with_tests: bool = False) -> tuple[str, RunResult]:
    result = result or Runner().run(document, fresh=fresh, with_tests=with_tests)
    by_id = {cell.id: cell for cell in result.cells}
    title = str(document.frontmatter.get("title", document.path.stem if document.path else "PMD report"))
    parts = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{html.escape(title)}</title><style>{STYLE}{SOURCE_STYLE}</style></head><body><main>",
    ]
    failing_tests = [cell.id for cell in result.cells if cell.status == "failed" and document.lookup[cell.id].role == "test"]
    if with_tests and failing_tests:
        message = "This render includes failing tests: " + ", ".join(failing_tests)
        parts.append(f'<div class="warning banner-failed">{html.escape(message)}</div>')
    cursor = document.body_start
    for cell in document.cells:
        parts.append(MARKDOWN.render(document.source[cursor:cell.start]))
        parts.append(_cell_html(cell, by_id.get(cell.id), document))
        cursor = cell.end
    parts.append(MARKDOWN.render(document.source[cursor:]))
    if result.errors:
        parts.append('<div class="warning">' + "<br>".join(html.escape(error) for error in result.errors) + "</div>")
    parts.append("</main></body></html>")
    return "".join(parts), result
