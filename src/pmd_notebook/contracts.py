from __future__ import annotations

import re
from typing import Any

from .models import Cell, Document

PRODUCE_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):schema#(?P<schema>[A-Za-z_][A-Za-z0-9_-]*)$")


def produced_contracts(cell: Cell) -> tuple[list[tuple[str, str]], list[str]]:
    contracts: list[tuple[str, str]] = []
    errors: list[str] = []
    for item in filter(None, (value.strip() for value in cell.attrs.get("produces", "").split(","))):
        match = PRODUCE_RE.fullmatch(item)
        if not match:
            errors.append(f"{cell.id}: invalid produces contract '{item}'")
        else:
            contracts.append((match.group("key"), match.group("schema")))
    return contracts, errors


def schema_definitions(document: Document) -> tuple[dict[str, dict[str, Any]], list[str]]:
    value = document.frontmatter.get("schemas", {})
    if value is None:
        return {}, []
    if not isinstance(value, dict):
        return {}, ["frontmatter schemas must be a mapping"]
    schemas: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for name, schema in value.items():
        if not isinstance(name, str) or not isinstance(schema, dict):
            errors.append(f"schema '{name}' must be a mapping")
        else:
            schemas[name] = schema
    return schemas, errors


def literal_ctx_reads(source: str) -> set[str]:
    reads = set(re.findall(r"\bctx\.([A-Za-z_][A-Za-z0-9_]*)", source))
    reads.update(re.findall(r"\bctx\.get\(\s*['\"]([^'\"]+)['\"]", source))
    reads.update(re.findall(r"\bctx\[\s*['\"]([^'\"]+)['\"]\s*\]", source))
    writes = set(re.findall(r"\bctx\.([A-Za-z_][A-Za-z0-9_]*)\s*=", source))
    writes.update(re.findall(r"\bctx\.set\(\s*['\"]([^'\"]+)['\"]", source))
    writes.update(re.findall(r"\bctx\[\s*['\"]([^'\"]+)['\"]\s*\]\s*=", source))
    return reads - writes - {"get", "set", "has"}


def validate_value(value: Any, schema: dict[str, Any], path: str = "value") -> list[str]:
    errors: list[str] = []
    expected = schema.get("type")
    types = {
        "null": lambda item: item is None,
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "string": lambda item: isinstance(item, str),
        "array": lambda item: isinstance(item, list),
        "object": lambda item: isinstance(item, dict),
    }
    if isinstance(expected, str) and expected in types and not types[expected](value):
        return [f"{path} must be {expected}"]
    if "enum" in schema and isinstance(schema["enum"], list) and value not in schema["enum"]:
        errors.append(f"{path} is not one of the allowed values")
    if isinstance(value, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            errors.extend(f"{path}.{key} is required" for key in required if key not in value)
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child in properties.items():
                if key in value and isinstance(child, dict):
                    errors.extend(validate_value(value[key], child, f"{path}.{key}"))
            if schema.get("additionalProperties") is False:
                errors.extend(f"{path}.{key} is not allowed" for key in value if key not in properties)
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(validate_value(item, schema["items"], f"{path}[{index}]"))
    return errors
