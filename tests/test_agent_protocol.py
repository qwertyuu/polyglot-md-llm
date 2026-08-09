from __future__ import annotations

import json
from pathlib import Path

from pmd_notebook.agent_protocol import (
    apply_transaction,
    capabilities,
    digest,
    inspect_document,
    read_source,
    verify_document,
)
from pmd_notebook.cli import main
from pmd_notebook.parser import load


NOTEBOOK = """---
pmd: "0.1"
title: Agent fixture
---
# Analysis

```python {#seed independent=true}
ctx.value = 2
```

```python {#compute depends-on=seed}
ctx.result = ctx.value * 2
```

```python {#report depends-on=compute}
print(ctx.result)
```

```python {#check role=test test-of=compute}
assert ctx.result == 4
```

```python {#unrelated independent=true}
raise RuntimeError("must not execute")
```
"""


def notebook(tmp_path: Path) -> Path:
    path = tmp_path / "analysis.pmd"
    path.write_text(NOTEBOOK, encoding="utf-8")
    return path


def configure_state(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PMD_AGENT_STATE_DIR", str(tmp_path / "agent-state"))
    monkeypatch.setenv("PMD_CACHE_DIR", str(tmp_path / "cache"))


def test_capabilities_advertise_complete_profile() -> None:
    outcome = capabilities()
    assert outcome.exit_code == 0
    assert outcome.response["result"]["profiles"][-1] == "llm-ready"
    assert "replace_cell_source" in outcome.response["result"]["operations"]


def test_inspect_returns_only_requested_neighborhood(tmp_path: Path) -> None:
    path = notebook(tmp_path)
    outcome = inspect_document(path, {
        "roots": ["compute"],
        "upstream_depth": 1,
        "downstream_depth": 1,
        "include_tests": True,
        "include_source": True,
        "include_narrative": "adjacent",
        "max_bytes": 16384,
    })
    assert outcome.response["ok"]
    cells = outcome.response["result"]["cells"]
    assert [cell["id"] for cell in cells] == ["seed", "compute", "report", "check"]
    compute = next(cell for cell in cells if cell["id"] == "compute")
    assert compute["dependencies"] == {"explicit": ["seed"], "resolved": ["seed"]}
    assert compute["source"]["included"]
    assert all(cell["content_trust"] == "untrusted" for cell in cells)


def test_inspect_omits_content_instead_of_truncating(tmp_path: Path) -> None:
    path = tmp_path / "large.pmd"
    path.write_text("```python {#large}\n" + "value = 1\n" * 1000 + "```\n", encoding="utf-8")
    outcome = inspect_document(path, {
        "include_source": True,
        "include_narrative": "all",
        "max_bytes": 2048,
    })
    assert outcome.response["ok"]
    assert outcome.response["result"]["omissions"]
    omitted = [cell["source"] for cell in outcome.response["result"]["cells"] if not cell["source"]["included"]]
    assert omitted
    assert all("text" not in item and item["digest"].startswith("sha256:") for item in omitted)
    assert len(json.dumps(outcome.response, separators=(",", ":")).encode()) <= 2048


def test_apply_replaces_one_cell_and_returns_change_token(monkeypatch, tmp_path: Path) -> None:
    configure_state(monkeypatch, tmp_path)
    path = notebook(tmp_path)
    original = read_source(path)
    parsed = load(path)
    outcome = apply_transaction(path, {
        "base_revision": original.revision,
        "operations": [{
            "op": "replace_cell_source",
            "cell_id": "compute",
            "expected_source_digest": digest(parsed.lookup["compute"].source),
            "source": "ctx.result = ctx.value * 3",
        }],
    })
    assert outcome.response["ok"]
    result = outcome.response["result"]
    assert result["change_token"]
    assert result["impact"]["affected"] == ["compute", "report"]
    assert result["impact"]["impacted_tests"] == ["check"]
    assert "# Analysis" in path.read_text(encoding="utf-8")
    assert load(path).lookup["compute"].source == "ctx.result = ctx.value * 3"


def test_apply_rejects_stale_revision_without_writing(monkeypatch, tmp_path: Path) -> None:
    configure_state(monkeypatch, tmp_path)
    path = notebook(tmp_path)
    before = path.read_bytes()
    outcome = apply_transaction(path, {
        "base_revision": "sha256:" + "0" * 64,
        "operations": [{"op": "delete_cell", "cell_id": "compute", "expected_source_digest": "sha256:none"}],
    })
    assert outcome.exit_code == 4
    assert outcome.response["errors"][0]["code"] == "revision_conflict"
    assert path.read_bytes() == before


def test_apply_is_atomic_when_candidate_is_invalid(monkeypatch, tmp_path: Path) -> None:
    configure_state(monkeypatch, tmp_path)
    path = notebook(tmp_path)
    source = read_source(path)
    before = source.raw
    outcome = apply_transaction(path, {
        "base_revision": source.revision,
        "operations": [{
            "op": "set_cell_attributes",
            "cell_id": "compute",
            "set": {"depends-on": "missing"},
            "remove": [],
        }],
    })
    assert outcome.response["errors"][0]["code"] == "transaction_invalid"
    assert path.read_bytes() == before


def test_apply_checks_response_budget_before_writing(monkeypatch, tmp_path: Path) -> None:
    configure_state(monkeypatch, tmp_path)
    path = notebook(tmp_path)
    source = read_source(path)
    before = source.raw
    outcome = apply_transaction(path, {
        "base_revision": source.revision,
        "max_response_bytes": 1024,
        "operations": [{
            "op": "replace_cell_source",
            "cell_id": "compute",
            "expected_source_digest": digest(load(path).lookup["compute"].source),
            "source": "ctx.result = 10",
        }],
    })
    assert outcome.response["errors"][0]["code"] == "response_budget_too_small"
    assert path.read_bytes() == before


def test_replace_narrative_cannot_smuggle_an_executable_cell(monkeypatch, tmp_path: Path) -> None:
    configure_state(monkeypatch, tmp_path)
    path = notebook(tmp_path)
    source = read_source(path)
    inspected = inspect_document(path, {"roots": ["seed"], "include_narrative": "adjacent"})
    narrative = inspected.response["result"]["narrative"][0]
    outcome = apply_transaction(path, {
        "base_revision": source.revision,
        "operations": [{
            "op": "replace_narrative",
            "segment_id": narrative["segment_id"],
            "expected_digest": narrative["digest"],
            "markdown": "```python {#smuggled}\nraise RuntimeError()\n```\n",
        }],
    })
    assert outcome.response["errors"][0]["code"] == "transaction_invalid"
    assert path.read_bytes() == source.raw


def test_apply_dry_run_returns_candidate_without_writing(monkeypatch, tmp_path: Path) -> None:
    configure_state(monkeypatch, tmp_path)
    path = notebook(tmp_path)
    source = read_source(path)
    outcome = apply_transaction(path, {
        "base_revision": source.revision,
        "dry_run": True,
        "operations": [{
            "op": "delete_cell",
            "cell_id": "unrelated",
            "expected_source_digest": digest(load(path).lookup["unrelated"].source),
        }],
    })
    assert outcome.response["ok"]
    assert not outcome.response["result"]["applied"]
    assert outcome.response["result"]["change_token"] is None
    assert outcome.response["result"]["new_revision"] != source.revision
    assert outcome.response["document"]["revision"] == source.revision
    assert path.read_bytes() == source.raw


def test_semantic_operations_update_references_and_frontmatter(monkeypatch, tmp_path: Path) -> None:
    configure_state(monkeypatch, tmp_path)
    path = notebook(tmp_path)
    source = read_source(path)
    frontmatter = inspect_document(path, {"include_frontmatter": True}).response["result"]["frontmatter"]["source"]
    outcome = apply_transaction(path, {
        "base_revision": source.revision,
        "operations": [
            {"op": "rename_cell", "cell_id": "compute", "new_cell_id": "calculate"},
            {"op": "set_cell_language", "cell_id": "calculate", "language": "python3"},
            {"op": "set_cell_attributes", "cell_id": "calculate", "set": {"tags": "agent"}, "remove": []},
            {"op": "insert_cell", "cell_id": "format", "language": "python", "source": "print('format')", "attributes": {"depends-on": "calculate"}, "before": "report"},
            {"op": "move_cell", "cell_id": "format", "after": "report"},
            {"op": "replace_frontmatter", "expected_digest": frontmatter["digest"], "yaml": "pmd: \"0.1\"\ntitle: Updated by agent\n"},
        ],
    })
    assert outcome.response["ok"], outcome.response
    parsed = load(path)
    assert parsed.lookup["calculate"].language == "python3"
    assert parsed.lookup["calculate"].attrs["tags"] == "agent"
    assert parsed.lookup["report"].attrs["depends-on"] == "calculate"
    assert parsed.lookup["check"].attrs["test-of"] == "calculate"
    assert parsed.frontmatter["title"] == "Updated by agent"


def test_verify_requires_authorization(monkeypatch, tmp_path: Path) -> None:
    configure_state(monkeypatch, tmp_path)
    path = notebook(tmp_path)
    outcome = verify_document(path, {
        "document_revision": read_source(path).revision,
        "changed_cells": ["compute"],
        "include_downstream": True,
        "tests": "impacted",
    }, allow_execution=False)
    assert outcome.exit_code == 5
    assert outcome.response["errors"][0]["code"] == "authorization_required"
    assert outcome.response["result"]["receipt"]["status"] == "blocked"


def test_apply_then_verify_runs_only_affected_graph(monkeypatch, tmp_path: Path) -> None:
    configure_state(monkeypatch, tmp_path)
    path = notebook(tmp_path)
    source = read_source(path)
    cell = load(path).lookup["compute"]
    applied = apply_transaction(path, {
        "base_revision": source.revision,
        "operations": [{
            "op": "replace_cell_source",
            "cell_id": "compute",
            "expected_source_digest": digest(cell.source),
            "source": "ctx.result = ctx.value * 2\nprint('changed')",
        }],
    })
    request = applied.response["result"]["recommended_verification"]
    verified = verify_document(path, request, allow_execution=True)
    assert verified.exit_code == 0, verified.response
    receipt = verified.response["result"]["receipt"]
    assert receipt["status"] == "verified"
    assert receipt["scope_source"] == "apply_transaction"
    assert [cell["cell_id"] for cell in receipt["cells"]] == ["seed", "compute", "report"]
    assert [test["cell_id"] for test in receipt["tests"]] == ["check"]
    assert "unrelated" not in verified.response["result"]["plan"]["execution_order"]
    executed = next(cell for cell in receipt["cells"] if cell["cell_id"] == "compute")
    assert executed["cache_key"]
    assert executed["started_at"].endswith("Z")
    assert executed["duration_seconds"] >= 0


def test_document_restriction_fails_closed_when_unenforceable(monkeypatch, tmp_path: Path) -> None:
    configure_state(monkeypatch, tmp_path)
    path = tmp_path / "restricted.pmd"
    path.write_text(
        """---
agent:
  restrictions:
    network: deny
---
```python {#work}
print("work")
```
""",
        encoding="utf-8",
    )
    outcome = verify_document(path, {
        "document_revision": read_source(path).revision,
        "changed_cells": ["work"],
    }, allow_execution=True)
    assert outcome.exit_code == 5
    assert outcome.response["errors"][0]["code"] == "policy_unenforceable"
    assert outcome.response["result"]["receipt"]["status"] == "blocked"


def test_verify_reports_test_failure(monkeypatch, tmp_path: Path) -> None:
    configure_state(monkeypatch, tmp_path)
    path = notebook(tmp_path)
    outcome = verify_document(path, {
        "document_revision": read_source(path).revision,
        "changed_cells": ["compute"],
        "include_downstream": True,
        "tests": "impacted",
        "fresh": True,
    }, allow_execution=True)
    assert outcome.exit_code == 0
    assert outcome.response["result"]["receipt"]["status"] == "verified"

    text = path.read_text(encoding="utf-8").replace("assert ctx.result == 4", "assert ctx.result == 999")
    path.write_text(text, encoding="utf-8")
    failed = verify_document(path, {
        "document_revision": read_source(path).revision,
        "changed_cells": ["check"],
        "include_downstream": True,
        "tests": "impacted",
        "fresh": True,
    }, allow_execution=True)
    assert failed.exit_code == 1
    assert failed.response["errors"][0]["code"] == "test_failed"
    assert failed.response["result"]["receipt"]["status"] == "failed"


def test_agent_cli_writes_one_json_document(capsys) -> None:
    try:
        main(["agent", "capabilities"])
    except SystemExit as error:
        assert error.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["command"] == "capabilities"

