from __future__ import annotations

import sys
from pathlib import Path

from pmd_notebook import Cache, Runner, graph_lines, parse, render_html, validate
from pmd_notebook.cli import main


def document(source: str, tmp_path: Path):
    return parse(source, tmp_path / "notebook.pmd")


def runner(tmp_path: Path) -> Runner:
    return Runner(Cache(tmp_path / "cache"))


def test_plain_markdown_without_cells_renders(tmp_path: Path) -> None:
    parsed = document("# Narrative\n\nA **plain** document.\n", tmp_path)
    page, result = render_html(parsed)
    assert result.ok
    assert not result.cells
    assert "<h1>Narrative</h1>" in page
    assert "<strong>plain</strong>" in page


def test_implicit_dependencies_skip_tests_and_scratch(tmp_path: Path) -> None:
    parsed = document(
        """```python {#first}
pass
```
```python {#probe role=test test-of=first}
pass
```
```python {#notes role=scratch}
pass
```
```python {#second}
pass
```
```python {#third independent=true}
pass
```
""",
        tmp_path,
    )
    assert parsed.lookup["second"].dependencies == ["first"]
    assert parsed.lookup["third"].dependencies == []
    assert graph_lines(parsed)[1] == "probe: first"


def test_validation_reports_all_static_errors(tmp_path: Path) -> None:
    parsed = document(
        """```unknown {#same mystery=yes depends-on=missing}
pass
```
```python {#same role=test}
pass
```
""",
        tmp_path,
    )
    errors = validate(parsed)
    assert "duplicate cell id: same" in errors
    assert "same: unknown attribute 'mystery'" in errors
    assert "same: no engine for 'unknown'" in errors
    assert "same: unresolved reference 'missing'" in errors
    assert "same: test cells require test-of" in errors


def test_cycle_is_reported_as_cell_sequence(tmp_path: Path) -> None:
    parsed = document(
        """```python {#a depends-on=b}
pass
```
```python {#b depends-on=a}
pass
```
""",
        tmp_path,
    )
    assert "dependency cycle: a -> b -> a" in validate(parsed)


def test_python_context_output_and_single_cell_closure(tmp_path: Path) -> None:
    parsed = document(
        """```python {#seed}
ctx.set("value", 6)
print("seed")
```
```python {#double}
ctx.result = ctx.value * 2
display.markdown(f"**{ctx.result}**", "result.md")
```
```python {#unused independent=true}
raise RuntimeError("must not run")
```
""",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, cell="double", fresh=True)
    assert result.ok
    assert [cell.id for cell in result.cells] == ["seed", "double"]
    assert result.cells[1].context == {"result": 12}
    assert result.cells[1].outputs[0].kind == "markdown"
    assert result.cells[1].outputs[0].data == b"**12**"


def test_unrelated_cell_cannot_observe_context(tmp_path: Path) -> None:
    parsed = document(
        """```python {#writer independent=true}
ctx.secret = 42
```
```python {#reader independent=true}
ctx.get("secret")
```
""",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, fresh=True)
    assert not result.ok
    assert result.cells[0].status == "passed"
    assert result.cells[1].status == "failed"
    assert "PMD ctx key not set: secret" in result.cells[1].stderr


def test_failure_blocks_only_downstream_cells(tmp_path: Path) -> None:
    parsed = document(
        """```python {#bad independent=true}
raise RuntimeError("broken")
```
```python {#blocked depends-on=bad}
print("no")
```
```python {#other independent=true}
print("yes")
```
""",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, fresh=True)
    assert [cell.status for cell in result.cells] == ["failed", "blocked", "passed"]
    assert "RuntimeError: broken" in result.cells[0].stderr


def test_expected_nonzero_exit_is_success(tmp_path: Path) -> None:
    parsed = document(
        f"```python {{#expected expect-exit-code=7}}\nimport sys; sys.exit(7)\n```\n",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, fresh=True)
    assert result.ok
    assert result.cells[0].exit_code == 7


def test_test_cells_report_independently_from_run(tmp_path: Path) -> None:
    parsed = document(
        """```python {#value}
ctx.value = 9
```
```python {#check role=test test-of=value}
assert ctx.value == 9
```
""",
        tmp_path,
    )
    normal = runner(tmp_path).run(parsed, fresh=True)
    tested = runner(tmp_path).run(parsed, tests=True, fresh=True)
    assert [cell.id for cell in normal.cells] == ["value"]
    assert [cell.id for cell in tested.cells] == ["value", "check"]
    assert tested.ok


def test_cache_reuses_dependencies_but_not_requested_target(tmp_path: Path) -> None:
    parsed = document(
        """```python {#one}
ctx.one = 1
```
```python {#two}
ctx.two = ctx.one + 1
```
""",
        tmp_path,
    )
    implementation = runner(tmp_path)
    first = implementation.run(parsed, cell="two")
    second = implementation.run(parsed, cell="two")
    assert first.ok and second.ok
    assert second.cells[0].status == "cached"
    assert second.cells[1].status == "passed"


def test_html_is_self_contained_and_includes_streams(tmp_path: Path) -> None:
    parsed = document(
        """# Report

```python {#make}
import os
open(os.path.join(os.environ['PMD_CELL_OUT'], 'data.csv'), 'w').write('a,b\\n1,2\\n')
print('hello')
```
""",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, fresh=True)
    page, _ = render_html(parsed, result)
    assert "hello" in page
    assert "<table>" in page
    assert "http://" not in page and "https://" not in page
    assert "PMD_CELL_OUT" in page
    assert '<span class="kn">import</span>' in page


def test_html_prioritizes_results_and_hides_empty_diagnostics(tmp_path: Path) -> None:
    parsed = document(
        """```python {#report}
print('A useful finding')
```
""",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, fresh=True)
    page, _ = render_html(parsed, result)
    assert 'class="result"' in page
    assert "A useful finding" in page
    assert "Technical details" not in page
    assert "stdout" not in page
    assert "stderr" not in page
    assert "View source" in page


def test_frontmatter_engine_override(tmp_path: Path) -> None:
    parsed = document(
        f"""---
pmd: "0.1"
engines:
  custom:
    command: '"{sys.executable}"'
---
```custom {{#cell}}
print("custom")
```
""",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, fresh=True)
    assert result.ok
    assert result.cells[0].stdout == "custom\n"


def test_sql_context_binding_crosses_into_python(tmp_path: Path) -> None:
    parsed = document(
        """```sql {#sql-value}
SELECT ctx_set('number', '14');
```
```python {#python-value}
assert ctx.number == 14
```
""",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, fresh=True)
    assert result.ok


def test_cli_test_reports_pass_only_for_test_cell(tmp_path: Path, capsys) -> None:
    path = tmp_path / "cli.pmd"
    path.write_text(
        """```python {#value}
ctx.value = 1
```
```python {#check role=test test-of=value}
assert ctx.value == 1
```
""",
        encoding="utf-8",
    )
    try:
        main(["test", str(path), "--fresh"])
    except SystemExit as error:
        assert error.code == 0
    output = capsys.readouterr().out.splitlines()
    assert output[0].startswith("PASSED  value")
    assert output[1].startswith("PASS    check")


def test_verbose_cli_prints_successful_stdout(tmp_path: Path, capsys) -> None:
    path = tmp_path / "verbose.pmd"
    path.write_text("```python {#hello}\nprint('visible output')\n```\n", encoding="utf-8")
    try:
        main(["run", str(path), "--fresh", "--verbose"])
    except SystemExit as error:
        assert error.code == 0
    captured = capsys.readouterr()
    assert "visible output" in captured.out


def test_output_directory_exports_rich_outputs(tmp_path: Path) -> None:
    parsed = document(
        """```python {#produce}
import os
from pathlib import Path
Path(os.environ["PMD_CELL_OUT"], "chart.txt").write_text("attachment", encoding="utf-8")
```
""",
        tmp_path,
    )
    export = tmp_path / "export"
    result = runner(tmp_path).run(parsed, fresh=True, output_dir=export)
    assert result.ok
    assert (export / "produce" / "chart.txt").read_text(encoding="utf-8") == "attachment"


def test_declared_input_change_invalidates_cache(tmp_path: Path) -> None:
    input_path = tmp_path / "input.txt"
    input_path.write_text("one", encoding="utf-8")
    parsed = document(
        """---
inputs: [input.txt]
---
```python {#read-input}
from pathlib import Path
ctx.value = Path("input.txt").read_text(encoding="utf-8")
```
""",
        tmp_path,
    )
    implementation = runner(tmp_path)
    first = implementation.run(parsed)
    second = implementation.run(parsed)
    input_path.write_text("two", encoding="utf-8")
    third = implementation.run(parsed)
    assert first.cells[0].status == "passed"
    assert second.cells[0].status == "cached"
    assert third.cells[0].status == "passed"
    assert third.cells[0].context["value"] == "two"


def test_document_relative_engine_command(tmp_path: Path) -> None:
    relative_python = Path(__import__("os").path.relpath(sys.executable, tmp_path)).as_posix()
    parsed = document(
        f"""---
engines:
  custom:
    command: '{{document_dir}}/{relative_python}'
---
```custom {{#portable}}
print("portable engine")
```
""",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, fresh=True)
    assert result.ok
    assert Path(result.cells[0].command[0]).resolve() == Path(sys.executable).resolve()
    assert result.cells[0].stdout == "portable engine\n"


def test_downstream_cell_can_inspect_dependency_outputs(tmp_path: Path) -> None:
    parsed = document(
        """```python {#produce}
import os
from pathlib import Path
Path(os.environ["PMD_CELL_OUT"], "value.txt").write_text("42", encoding="utf-8")
```
```python {#inspect-output role=test test-of=produce}
assert outputs.path("produce", "value.txt").read_text(encoding="utf-8") == "42"
print("dependency attachment is readable")
```
""",
        tmp_path,
    )
    implementation = runner(tmp_path)
    first = implementation.run(parsed, tests=True, fresh=True)
    second = implementation.run(parsed, tests=True, cell="inspect-output")
    assert first.ok and second.ok
    assert second.cells[0].status == "cached"
    assert second.cells[1].status == "passed"
