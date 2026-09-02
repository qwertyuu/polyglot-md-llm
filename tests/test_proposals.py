from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from pathlib import Path

from pmd_notebook import Cache, Runner, inspect_document, lint_inputs, parse, render_html, render_text, validate
from pmd_notebook.cli import _ensure_utf8_streams, main


def document(source: str, tmp_path: Path):
    return parse(source, tmp_path / "notebook.pmd")


def runner(tmp_path: Path) -> Runner:
    return Runner(Cache(tmp_path / "cache"))


# Proposal 0001 -----------------------------------------------------------

def test_non_ascii_cell_source_round_trips(tmp_path: Path) -> None:
    parsed = document(
        '```python {#emdash}\nprint("em dash: —")\n```\n',
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, fresh=True)
    assert result.ok
    assert "—" in result.cells[0].stdout


def test_ensure_utf8_streams_makes_narrow_encoded_stream_safe() -> None:
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict")
    try:
        stream.write("cjk: 中文")
        raise AssertionError("expected UnicodeEncodeError on an unpatched cp1252 stream")
    except UnicodeEncodeError:
        pass

    _ensure_utf8_streams([stream])
    stream.write("cjk: 中文 emoji: \U0001F600")
    stream.flush()
    buffer.seek(0)
    assert "中文" in buffer.read().decode("utf-8")


def test_ensure_utf8_streams_tolerates_streams_without_reconfigure() -> None:
    _ensure_utf8_streams([object()])


# Proposal 0002 -------------------------------------------------------------

def test_lib_cell_composes_source_into_user_and_invalidates_cache(tmp_path: Path) -> None:
    parsed = document(
        """```python {#consts role=lib}
BOT_SIDE = {"a": "light"}
```
```python {#roster uses=consts}
ctx.side = BOT_SIDE["a"]
```
""",
        tmp_path,
    )
    implementation = runner(tmp_path)
    first = implementation.run(parsed)
    assert first.ok
    assert [cell.id for cell in first.cells] == ["roster"]
    assert first.cells[0].context == {"side": "light"}

    second = implementation.run(parsed)
    assert second.cells[0].status == "cached"

    edited = document(
        """```python {#consts role=lib}
BOT_SIDE = {"a": "dark"}
```
```python {#roster uses=consts}
ctx.side = BOT_SIDE["a"]
```
""",
        tmp_path,
    )
    third = implementation.run(edited)
    assert third.cells[0].status == "passed"
    assert third.cells[0].context == {"side": "dark"}


def test_lib_cell_excluded_from_roots_and_cannot_be_cell_target(tmp_path: Path) -> None:
    parsed = document(
        """```python {#consts role=lib}
X = 1
```
```python {#user uses=consts}
ctx.x = X
```
""",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, fresh=True)
    assert [cell.id for cell in result.cells] == ["user"]

    rejected = runner(tmp_path).run(parsed, cell="consts", fresh=True)
    assert not rejected.ok
    assert "requires a code or setup cell" in rejected.errors[0]


def test_uses_validation_rejects_bad_role_language_and_lib_attributes(tmp_path: Path) -> None:
    wrong_role = document(
        """```python {#user uses=missing}
pass
```
""",
        tmp_path,
    )
    assert any("unresolved reference 'missing'" in error for error in validate(wrong_role))

    not_lib = document(
        """```python {#helper}
pass
```
```python {#user uses=helper}
pass
```
""",
        tmp_path,
    )
    assert any("must be role=lib" in error for error in validate(not_lib))

    cross_language = document(
        """```python {#consts role=lib}
X = 1
```
```bash {#user uses=consts}
echo hi
```
""",
        tmp_path,
    )
    assert any("has language 'python', expected 'bash'" in error for error in validate(cross_language))

    lib_with_depends_on = document(
        """```python {#consts role=lib depends-on=missing}
X = 1
```
""",
        tmp_path,
    )
    assert any("depends-on does not apply to role=lib" in error for error in validate(lib_with_depends_on))


# Proposal 0003 ---------------------------------------------------------

def test_render_with_tests_executes_and_reports_pass_fail(tmp_path: Path) -> None:
    passing = document(
        """```python {#value}
ctx.value = 1
```
```python {#check role=test test-of=value}
assert ctx.value == 1
```
""",
        tmp_path,
    )
    default_page, default_result = render_html(passing, fresh=True)
    assert [cell.id for cell in default_result.cells] == ["value"]
    assert "not-run" in default_page

    wt_page, wt_result = render_html(passing, fresh=True, with_tests=True)
    assert [cell.id for cell in wt_result.cells] == ["value", "check"]
    assert wt_result.ok
    assert "status-passed" in wt_page


def test_render_with_tests_failure_still_renders_and_exits_nonzero(tmp_path: Path, capsys) -> None:
    path = tmp_path / "failing.pmd"
    path.write_text(
        """```python {#value}
ctx.value = 1
```
```python {#check role=test test-of=value}
assert ctx.value == 999
```
""",
        encoding="utf-8",
    )
    try:
        main(["render", str(path), "--to", "html", "--fresh", "--with-tests"])
    except SystemExit as error:
        assert error.code == 1
    destination = path.with_suffix(".html")
    assert destination.exists()
    assert "banner-failed" in destination.read_text(encoding="utf-8")


# Proposal 0004 -----------------------------------------------------------

def test_lint_inputs_flags_undeclared_literal_and_stale_declaration(tmp_path: Path) -> None:
    (tmp_path / "declared.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    parsed = document(
        """---
inputs: [declared.csv, unused.json]
---
```python {#read}
open("declared.csv")
open("undeclared.parquet")
url = "https://example.com/data.csv"
```
""",
        tmp_path,
    )
    warnings = lint_inputs(parsed)
    assert any("undeclared.parquet" in item for item in warnings)
    assert any("unused.json" in item and "does not appear to be referenced" in item for item in warnings)
    assert not any("declared.csv" in item for item in warnings)
    assert not any("example.com" in item for item in warnings)


def test_lint_inputs_precision_retune_avoids_known_false_positive_categories(tmp_path: Path) -> None:
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "chart.png").write_bytes(b"x")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "player_game_risk.parquet").write_bytes(b"x")
    parsed = document(
        """---
inputs: ["output/chart.png"]
---
```python {#a}
# category 1: display.*'s name= kwarg is a destination filename, not an input
display.image("output/chart.png", name="chart.png")

# category 2: a leading escape sequence spacing idiom
print("\\nSummary of results:")

# category 3: a numeric fraction in prose, not a path
print("fewer than 8/12 bots showed the effect")

# genuine undeclared read - the positive control
import pandas as pd
df = pd.read_parquet("data/player_game_risk.parquet")
```
""",
        tmp_path,
    )
    warnings = lint_inputs(parsed)
    assert warnings == ["a: literal path 'data/player_game_risk.parquet' is not covered by frontmatter inputs:"]


def test_lint_inputs_does_not_flag_fstring_interpolation_adjacent_to_a_separator(tmp_path: Path) -> None:
    # Regression: TOKEN_STRIP_CHARS used to strip '{'/'}' before the
    # unresolved-interpolation guard ran, so a token like "{n_flagged}/12"
    # lost the very brace that should have excluded it.
    parsed = document(
        """```python {#a}
n_flagged_by_10 = 8
print(f"{n_flagged_by_10}/12 bots flagged")
```
""",
        tmp_path,
    )
    assert lint_inputs(parsed) == []


def test_lint_inputs_does_not_flag_floor_division_in_fstring(tmp_path: Path) -> None:
    # Regression: same brace-stripping bug also newly flagged
    # f"{len(games)//2}"-style floor division that the pre-retune,
    # whole-literal heuristic had excluded by accident.
    parsed = document(
        """```python {#a}
games = list(range(24))
print(f"still confirmed after removing {len(games)//2} games")
```
""",
        tmp_path,
    )
    assert lint_inputs(parsed) == []


def test_lint_inputs_never_affects_check_exit_code(tmp_path: Path, capsys) -> None:
    path = tmp_path / "notebook.pmd"
    path.write_text(
        """```python {#a}
open("missing.parquet")
```
""",
        encoding="utf-8",
    )
    try:
        main(["check", str(path), "--lint-inputs"])
    except SystemExit as error:
        assert error.code == 0
    captured = capsys.readouterr()
    assert "missing.parquet" in captured.err
    assert "PMD document is valid" in captured.out


# Proposal 0005 -----------------------------------------------------------

def test_patch_run_executes_replacement_source_without_caching_or_leaking(tmp_path: Path) -> None:
    parsed = document(
        """```python {#one}
ctx.value = 1
```
```python {#two}
ctx.result = ctx.value + 1
print("normal:", ctx.result)
```
""",
        tmp_path,
    )
    implementation = runner(tmp_path)
    baseline = implementation.run(parsed, fresh=True)
    assert baseline.ok

    patched = implementation.run(parsed, cell="two", patch='print("patched:", ctx.value + 100)')
    assert patched.ok
    two = next(cell for cell in patched.cells if cell.id == "two")
    one = next(cell for cell in patched.cells if cell.id == "one")
    assert "patched: 101" in two.stdout
    assert two.cache_key is None
    assert one.status == "cached"

    again = implementation.run(parsed, cell="two", patch='print("patched:", ctx.value + 100)')
    two_again = next(cell for cell in again.cells if cell.id == "two")
    assert two_again.status != "cached"

    unpatched = implementation.run(parsed, cell="two")
    two_unpatched = next(cell for cell in unpatched.cells if cell.id == "two")
    assert "normal:" in two_unpatched.stdout


def test_patch_requires_cell(tmp_path: Path) -> None:
    parsed = document(
        """```python {#one}
ctx.value = 1
```
""",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, patch="print('x')")
    assert not result.ok
    assert result.errors == ["--patch requires --cell"]


def test_cli_patch_without_cell_is_usage_error(tmp_path: Path, capsys) -> None:
    path = tmp_path / "notebook.pmd"
    path.write_text("```python {#one}\nctx.value = 1\n```\n", encoding="utf-8")
    try:
        main(["run", str(path), "--patch", "-"])
    except SystemExit as error:
        assert error.code == 3


# Proposal 0008 -----------------------------------------------------------

def test_render_keeps_captured_stdout_monospace(tmp_path: Path) -> None:
    parsed = document(
        '```python {#aligned}\nprint("name  value\\na     1")\n```\n',
        tmp_path,
    )
    page, result = render_html(parsed, fresh=True)
    assert result.ok
    assert '.result pre{margin:0;font-family:"Cascadia Mono"' in page
    assert ".result pre{margin:0;font:inherit}" not in page


def test_render_supports_markdown_tables_in_narrative_and_outputs(tmp_path: Path) -> None:
    parsed = document(
        """| a | b |
|---|---:|
| narrative | 1.00 |

```python {#table}
display.markdown("| a | b |\\n|---|---:|\\n| output | 2.00 |\\n")
```
""",
        tmp_path,
    )
    page, result = render_html(parsed, fresh=True)
    assert result.ok
    assert page.count("<table>") == 2
    assert "<td>narrative</td>" in page
    assert "<td>output</td>" in page


# Proposal 0009 -----------------------------------------------------------

def test_display_csv_serializes_list_of_dicts(tmp_path: Path) -> None:
    parsed = document(
        """```python {#csv_rows}
display.csv([{"Tier": "x", "M1": 4}, {"Tier": "y", "M2": 5}], "rows.csv")
```
""",
        tmp_path,
    )
    page, result = render_html(parsed, fresh=True)
    assert result.ok
    assert "<th>Tier</th>" in page
    assert "<th>M1</th>" in page
    assert "<th>M2</th>" in page
    assert "<td>x</td>" in page
    assert "<td>5</td>" in page


def test_display_csv_rejects_ambiguous_values(tmp_path: Path) -> None:
    parsed = document(
        '```python {#bad_csv}\ndisplay.csv({"a": 1, "b": 2}, "bad.csv")\n```\n',
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, fresh=True)
    assert not result.ok
    assert result.cells[0].status == "failed"
    assert "display.csv expects CSV text or a list of dictionaries" in result.cells[0].stderr


# Proposal 0011 -----------------------------------------------------------

def test_documentary_language_fences_remain_narrative(tmp_path: Path) -> None:
    source = "\n".join(
        f"```{language}\nexample\n```"
        for language in ("text", "console", "json", "yaml", "diff", "log", "toml")
    )
    parsed = document(source, tmp_path)
    assert parsed.cells == []
    assert validate(parsed) == []
    page, result = render_html(parsed)
    assert result.ok
    assert '<code class="language-json">example\n</code>' in page


def test_annotated_documentary_fence_explicitly_opts_into_cell_semantics(tmp_path: Path) -> None:
    parsed = document('```json {#payload}\n{"a": 1}\n```\n', tmp_path)
    assert [cell.id for cell in parsed.cells] == ["payload"]
    assert "payload: no engine for 'json'" in validate(parsed)


# Proposal 0013 -----------------------------------------------------------

def test_text_render_reflects_reader_view_without_graph_or_source(tmp_path: Path) -> None:
    parsed = document(
        """# Decision

| option | score |
|---|---:|
| A | 7 |

```python {#measure}
print("aligned  10")
display.markdown("**Verdict:** keep A")
```
""",
        tmp_path,
    )
    rendered, result = render_text(parsed, fresh=True)
    assert result.ok
    assert "Decision" in rendered
    assert "option\tscore" in rendered
    assert "A\t7" in rendered
    assert "aligned  10" in rendered
    assert "Verdict: keep A" in rendered
    assert "|---" not in rendered
    assert "Cell graph" not in rendered
    assert 'print("aligned  10")' not in rendered


def test_cli_renders_text_to_default_destination(tmp_path: Path) -> None:
    path = tmp_path / "report.pmd"
    path.write_text("# Report\n\n```python\nprint('visible')\n```\n", encoding="utf-8")
    try:
        main(["render", str(path), "--to", "text", "--fresh"])
    except SystemExit as error:
        assert error.code == 0
    destination = path.with_suffix(".txt")
    assert destination.exists()
    assert "visible" in destination.read_text(encoding="utf-8")


# Proposal 0014 -----------------------------------------------------------

def test_document_test_can_assert_reader_visible_text(tmp_path: Path) -> None:
    parsed = document(
        """```python {#table}
display.markdown("| a | b |\\n|---|---:|\\n| x | 1 |\\n")
```
```python {#document_ok role=test test-of=document}
assert "|---" not in rendered.text
assert "a\\tb" in rendered.text
assert "x\\t1" in rendered.text
```
""",
        tmp_path,
    )
    assert parsed.lookup["document_ok"].dependencies == ["table"]
    result = runner(tmp_path).run(parsed, tests=True, fresh=True)
    assert result.ok
    assert [cell.id for cell in result.cells] == ["table", "document_ok"]


def test_document_test_failure_is_reported_normally(tmp_path: Path) -> None:
    parsed = document(
        """# Visible title

```python {#document_bad role=test test-of=document}
assert "missing phrase" in rendered.text
```
""",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, tests=True, fresh=True)
    assert not result.ok
    assert result.cells[-1].status == "failed"


# Proposal 0015 -----------------------------------------------------------

def test_cli_can_hide_graph_and_source_for_reader_html(tmp_path: Path) -> None:
    path = tmp_path / "reader.pmd"
    path.write_text("# Reader\n\n```python {#work}\nprint('result')\n```\n", encoding="utf-8")
    destination = tmp_path / "reader-view.html"
    try:
        main([
            "render", str(path), "--to", "html", "--out", str(destination),
            "--hide-graph", "--hide-source", "--fresh",
        ])
    except SystemExit as error:
        assert error.code == 0
    page = destination.read_text(encoding="utf-8")
    assert "Cell graph" not in page
    assert "View source" not in page
    assert "result" in page


def test_default_html_keeps_developer_graph_and_source(tmp_path: Path) -> None:
    parsed = document("```python {#work}\nprint('result')\n```\n", tmp_path)
    page, result = render_html(parsed, fresh=True)
    assert result.ok
    assert "Cell graph" in page
    assert "View source" in page


# Proposal 0017 -----------------------------------------------------------

def test_stale_after_is_validated(tmp_path: Path) -> None:
    parsed = document("```python {#measure stale-after=soon}\npass\n```\n", tmp_path)
    assert "measure: invalid stale-after 'soon'" in validate(parsed)


def test_render_marks_old_measurement_as_stale(tmp_path: Path) -> None:
    parsed = document("```python {#measure stale-after=1d}\nprint('value')\n```\n", tmp_path)
    result = runner(tmp_path).run(parsed, fresh=True)
    result.cells[0].started_at = "2020-01-01T00:00:00Z"
    page, _ = render_html(parsed, result)
    assert 'class="warning measurement-age stale"' in page
    assert "stale after 1d" in page


def test_check_warns_when_last_matching_measurement_is_stale(monkeypatch, tmp_path: Path, capsys) -> None:
    path = tmp_path / "measure.pmd"
    path.write_text("```python {#measure stale-after=1d}\nprint('value')\n```\n", encoding="utf-8")
    parsed = parse(path.read_text(encoding="utf-8"), path)
    cache = Cache(tmp_path / "cache")
    old = runner(tmp_path).run(parsed, fresh=True).cells[0]
    old.started_at = "2020-01-01T00:00:00Z"
    cache.store("old-measure", old, parsed, parsed.lookup["measure"])
    monkeypatch.setenv("PMD_CACHE_DIR", str(tmp_path / "cache"))
    try:
        main(["check", str(path)])
    except SystemExit as error:
        assert error.code == 0
    assert "measurement is stale" in capsys.readouterr().err


# Proposal 0018 -----------------------------------------------------------

def test_run_context_override_is_nested_scoped_and_cache_keyed(tmp_path: Path) -> None:
    parsed = document(
        """```python {#scenario}
print(ctx.tuiles["canada"])
```
""",
        tmp_path,
    )
    implementation = runner(tmp_path)
    first = implementation.run(parsed, context_overrides={"tuiles": {"canada": 1400}})
    second = implementation.run(parsed, context_overrides={"tuiles": {"canada": 1600}})
    assert first.ok and second.ok
    assert first.cells[0].stdout.strip() == "1400"
    assert second.cells[0].stdout.strip() == "1600"
    assert first.cells[0].cache_key != second.cells[0].cache_key


def test_cli_sweep_runs_each_context_variant(tmp_path: Path, capsys) -> None:
    path = tmp_path / "sweep.pmd"
    path.write_text('```python {#scenario}\nprint(ctx.tuiles["canada"])\n```\n', encoding="utf-8")
    try:
        main(["run", str(path), "--sweep", "tuiles.canada=1400,1568,1800", "--verbose"])
    except SystemExit as error:
        assert error.code == 0
    output = capsys.readouterr().out
    assert "tuiles.canada=1400" in output
    assert "tuiles.canada=1568" in output
    assert "tuiles.canada=1800" in output
    assert "1400" in output and "1568" in output and "1800" in output


# Proposal 0019 -----------------------------------------------------------

def test_run_history_compares_observable_cell_outputs(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache")
    implementation = Runner(cache)
    first_document = document("```python {#value}\nprint('one')\n```\n", tmp_path)
    first = implementation.run(first_document, fresh=True)
    assert first.run_id

    second_document = document("```python {#value}\nprint('two')\n```\n", tmp_path)
    second = implementation.run(second_document, fresh=True)
    changes = cache.compare_run(second_document, second, first.run_id)
    assert changes == ["value: stdout changed"]


def test_run_history_rejects_another_document(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache")
    first = parse("```python {#value}\npass\n```\n", tmp_path / "first.pmd")
    second = parse("```python {#value}\npass\n```\n", tmp_path / "second.pmd")
    previous = Runner(cache).run(first, fresh=True)
    current = Runner(cache).run(second, fresh=True)
    try:
        cache.compare_run(second, current, previous.run_id)
        raise AssertionError("expected another-document comparison to fail")
    except ValueError as error:
        assert "another document" in str(error)


# Proposal 0021 -----------------------------------------------------------

CONTRACT_FRONTMATTER = """---
schemas:
  totals:
    type: object
    required: [Minimal]
    properties:
      Minimal: {type: number}
    additionalProperties: false
---
"""


def test_contract_check_detects_producer_outside_dependency_closure(tmp_path: Path) -> None:
    parsed = document(
        CONTRACT_FRONTMATTER + """
```python {#producer produces=totaux:schema#totals independent=true}
ctx.totaux = {"Minimal": 7.18}
```
```python {#consumer independent=true}
print(ctx.totaux)
```
""",
        tmp_path,
    )
    assert "consumer: ctx key 'totaux' is produced by 'producer' outside its dependency closure" in validate(parsed)


def test_runtime_contract_rejects_missing_or_invalid_output(tmp_path: Path) -> None:
    missing = document(
        CONTRACT_FRONTMATTER + """
```python {#producer produces=totaux:schema#totals}
pass
```
""",
        tmp_path,
    )
    missing_result = runner(tmp_path).run(missing, fresh=True)
    assert not missing_result.ok
    assert "declared ctx output was not produced: totaux" in missing_result.cells[0].stderr

    invalid = document(
        CONTRACT_FRONTMATTER + """
```python {#producer produces=totaux:schema#totals}
ctx.totaux = {"Minimal": "seven"}
```
""",
        tmp_path,
    )
    invalid_result = runner(tmp_path).run(invalid, fresh=True)
    assert not invalid_result.ok
    assert "ctx.totaux.Minimal must be number" in invalid_result.cells[0].stderr


def test_runtime_contract_accepts_valid_typed_output(tmp_path: Path) -> None:
    parsed = document(
        CONTRACT_FRONTMATTER + """
```python {#producer produces=totaux:schema#totals}
ctx.totaux = {"Minimal": 7.18}
```
""",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, fresh=True)
    assert result.ok
    assert result.cells[0].context["totaux"] == {"Minimal": 7.18}


# Proposal 0022 -----------------------------------------------------------

def test_cli_calls_notebook_and_returns_only_declared_json(tmp_path: Path, capsys) -> None:
    path = tmp_path / "callable.pmd"
    path.write_text(
        """---
schemas:
  totals: {type: object}
---
```python {#calculate produces=totaux:schema#totals}
ctx.totaux = {"Minimal": round(ctx.tuiles["canada"] / 200, 2)}
```
""",
        encoding="utf-8",
    )
    main([
        "call", str(path), "--input", '{"tuiles":{"canada":1600}}',
        "--output", "totaux", "--fresh",
    ])
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"Minimal": 8.0}
    assert "PASSED" not in captured.out


def test_cli_call_rejects_undeclared_output(tmp_path: Path, capsys) -> None:
    path = tmp_path / "callable.pmd"
    path.write_text("```python {#work}\nctx.internal = 1\n```\n", encoding="utf-8")
    try:
        main(["call", str(path), "--output", "internal"])
    except SystemExit as error:
        assert error.code == 3
    assert "not declared" in capsys.readouterr().err


# Proposal 0023 -----------------------------------------------------------

def test_check_lints_literal_hosts_against_declared_capabilities(tmp_path: Path) -> None:
    parsed = document(
        """---
capabilities:
  network: [api.example.com]
  ssh: [10.1.1.20]
---
```python {#network}
url = "https://api.example.com/data"
other = "https://undeclared.example/data"
```
```bash {#remote}
ssh user@10.1.1.20 uptime
```
""",
        tmp_path,
    )
    diagnostics = validate(parsed)
    assert "warning: literal network host is not declared in capabilities.network: undeclared.example" in diagnostics
    assert not any("api.example.com" in item for item in diagnostics)
    assert not any("10.1.1.20" in item for item in diagnostics)


def test_agent_inspect_exposes_declared_capabilities(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "capabilities.pmd"
    path.write_text(
        """---
capabilities:
  network: [api.example.com]
  ssh: [10.1.1.20]
---
```python {#work}
pass
```
""",
        encoding="utf-8",
    )
    outcome = inspect_document(path, {"roots": ["work"]})
    assert outcome.response["result"]["summary"]["capabilities"] == {
        "network": ["api.example.com"],
        "ssh": ["10.1.1.20"],
    }


# Proposal 0024 -----------------------------------------------------------

def test_cache_key_includes_resolved_engine_identity(monkeypatch, tmp_path: Path) -> None:
    import pmd_notebook.runner as runner_module

    parsed = document("```python {#work}\npass\n```\n", tmp_path)
    cache = Cache(tmp_path / "cache")
    cell = parsed.lookup["work"]
    monkeypatch.setattr(runner_module, "_engine_identity", lambda command: {"version": "one"})
    first = cache.key(cell, ["python"], {}, cell.source)
    monkeypatch.setattr(runner_module, "_engine_identity", lambda command: {"version": "two"})
    second = cache.key(cell, ["python"], {}, cell.source)
    assert first != second


def test_typed_output_contract_preserves_and_reuses_cache_key(tmp_path: Path) -> None:
    parsed = document(
        """---
schemas:
  value: {type: integer}
---
```python {#work produces=result:schema#value}
ctx.result = 42
```
""",
        tmp_path,
    )
    cache = Cache(tmp_path / "cache")
    executor = Runner(cache)

    first = executor.run(parsed, fresh=True)
    cache_key = first.cells[0].cache_key
    assert cache_key is not None
    assert len(cache_key) == 64
    assert all(character in "0123456789abcdef" for character in cache_key)
    assert (cache.directory / f"{cache_key}.json").is_file()

    second = executor.run(parsed)
    assert second.cells[0].status == "cached"
    assert second.cells[0].cache_key == cache_key
    assert second.cells[0].context == {"result": 42}


def test_cli_attest_binds_verified_receipt_to_document(tmp_path: Path, capsys) -> None:
    from pmd_notebook.agent_protocol import read_source

    path = tmp_path / "attested.pmd"
    path.write_text("# Evidence\n", encoding="utf-8")
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps({
        "status": "verified",
        "document_revision": read_source(path).revision,
        "receipt_id": "sha256:receipt",
        "plan_id": "sha256:plan",
        "runner": {"name": "polyglot-pmd", "version": "0.5.0"},
        "inputs": [], "cells": [], "tests": [],
    }), encoding="utf-8")
    main(["attest", str(path), "--receipt", str(receipt_path)])
    statement = json.loads(capsys.readouterr().out)
    assert statement["_type"] == "https://in-toto.io/Statement/v1"
    assert statement["predicateType"] == "https://slsa.dev/provenance/v1"
    assert statement["subject"][0]["digest"]["sha256"] == read_source(path).revision.removeprefix("sha256:")
    assert statement["predicate"]["pmd"]["unsigned"] is True


# Proposal 0025 -----------------------------------------------------------

def test_agent_stream_requires_authorization(tmp_path: Path, capsys) -> None:
    path = tmp_path / "stream.pmd"
    path.write_text("```python {#work}\npass\n```\n", encoding="utf-8")
    try:
        main(["agent", "run", str(path), "--stream"])
    except SystemExit as error:
        assert error.code == 5
    event = json.loads(capsys.readouterr().out)
    assert event["event"] == "run_blocked"
    assert event["code"] == "authorization_required"


def test_agent_stream_emits_ordered_ndjson_events(tmp_path: Path, capsys) -> None:
    path = tmp_path / "stream.pmd"
    path.write_text("```python {#one}\nprint('one')\n```\n```python {#two}\nprint('two')\n```\n", encoding="utf-8")
    try:
        main(["agent", "run", str(path), "--stream", "--allow-execution", "--fresh"])
    except SystemExit as error:
        assert error.code == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["event"] for event in events] == [
        "run_started", "cell_started", "cell_finished", "cell_started", "cell_finished", "run_finished",
    ]
    assert [event["id"] for event in events if event["event"] == "cell_finished"] == ["one", "two"]
    assert all(event["source_digest"].startswith("sha256:") for event in events if event["event"] == "cell_finished")


# Proposal 0026 -----------------------------------------------------------

def test_python_failure_reports_cell_relative_line_and_resolved_context(tmp_path: Path) -> None:
    parsed = document(
        """```python {#seed}
ctx.available = 42
```
```python {#broken}
print(ctx.missing)
```
""",
        tmp_path,
    )
    result = runner(tmp_path).run(parsed, fresh=True)
    failure = result.cells[-1].failure
    assert failure["kind"] == "exception"
    assert failure["exception_type"] == "KeyError"
    assert failure["line"] == 1
    assert failure["source_line"] == "print(ctx.missing)"
    assert failure["resolved_context"] == {"available": 42}


def test_stream_propagates_structured_failure(tmp_path: Path, capsys) -> None:
    path = tmp_path / "failure-stream.pmd"
    path.write_text("```python {#broken}\nraise ValueError('bad input')\n```\n", encoding="utf-8")
    try:
        main(["agent", "run", str(path), "--stream", "--allow-execution", "--fresh"])
    except SystemExit as error:
        assert error.code == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    finished = next(event for event in events if event["event"] == "cell_finished")
    assert finished["failure"]["exception_type"] == "ValueError"
    assert finished["failure"]["line"] == 1
