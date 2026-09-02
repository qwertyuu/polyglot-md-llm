from pathlib import Path

import yaml

from pmd_notebook import __version__
from pmd_notebook.agent_protocol import capabilities


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "polyglot-pmd" / "SKILL.md"


def read_skill() -> tuple[dict, str]:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, frontmatter, body = text.split("---\n", 2)
    return yaml.safe_load(frontmatter), body


def test_agent_skill_has_valid_identity_and_release_baseline() -> None:
    frontmatter, body = read_skill()

    assert frontmatter["name"] == "polyglot-pmd"
    assert ".pmd" in frontmatter["description"]
    assert frontmatter["metadata"]["pmd-version"] == __version__
    assert frontmatter["metadata"]["agent-protocol"] in body
    assert "pmd --version" in body
    assert "pmd agent capabilities" in body


def test_agent_skill_tracks_public_agent_capabilities() -> None:
    frontmatter, body = read_skill()
    result = capabilities().response["result"]

    assert frontmatter["metadata"]["agent-protocol"] == result["protocol_versions"][0]
    for field in ("protocol_versions", "profiles", "commands", "features", "operations"):
        for value in result[field]:
            assert value in body, f"SKILL.md is missing {field} entry {value!r}"
