from __future__ import annotations

import io

from pathlib import Path

from pmd_notebook import Cache, Runner, lint_inputs, parse, render_html, validate
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
