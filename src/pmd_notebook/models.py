from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Cell:
    id: str
    language: str
    source: str
    attrs: dict[str, str]
    index: int
    start: int
    end: int
    dependencies: list[str] = field(default_factory=list)

    @property
    def role(self) -> str:
        return self.attrs.get("role", "code")

    @property
    def tags(self) -> set[str]:
        return {value for value in self.attrs.get("tags", "").split(",") if value}

    @property
    def uses(self) -> list[str]:
        return [item.strip() for item in self.attrs.get("uses", "").split(",") if item.strip()]

    @property
    def skipped(self) -> bool:
        return self.attrs.get("skip", "false").lower() == "true"


@dataclass(slots=True)
class Document:
    source: str
    frontmatter: dict[str, Any]
    cells: list[Cell]
    diagnostics: list[str] = field(default_factory=list)
    path: Path | None = None
    body_start: int = 0

    @property
    def lookup(self) -> dict[str, Cell]:
        return {cell.id: cell for cell in self.cells}


@dataclass(slots=True)
class RichOutput:
    name: str
    kind: str
    data: bytes


@dataclass(slots=True)
class CellResult:
    id: str
    status: str
    command: list[str]
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    outputs: list[RichOutput] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    cached: bool = False
    cache_key: str | None = None
    started_at: str | None = None
    duration_seconds: float | None = None
    failure: dict[str, Any] | None = None


@dataclass(slots=True)
class RunResult:
    document: Document
    cells: list[CellResult]
    errors: list[str] = field(default_factory=list)
    run_id: str | None = None

    @property
    def ok(self) -> bool:
        return not self.errors and all(cell.status in {"passed", "cached"} for cell in self.cells)
