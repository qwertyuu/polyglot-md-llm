from __future__ import annotations

import re
from typing import Any

from .models import Document

HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")


def declared_capabilities(document: Document) -> tuple[dict[str, list[str]], list[str]]:
    value = document.frontmatter.get("capabilities", {})
    if value is None:
        return {}, []
    if not isinstance(value, dict):
        return {}, ["frontmatter capabilities must be a mapping"]
    errors: list[str] = []
    normalized: dict[str, list[str]] = {}
    for key in value:
        if key not in {"network", "ssh"}:
            errors.append(f"unknown capability '{key}'")
    for key in ("network", "ssh"):
        hosts = value.get(key, [])
        if not isinstance(hosts, list) or not all(isinstance(host, str) and HOST_RE.fullmatch(host) for host in hosts):
            errors.append(f"capabilities.{key} must be a list of host names or addresses")
        elif hosts:
            normalized[key] = list(dict.fromkeys(host.lower() for host in hosts))
    return normalized, errors


def capability_warnings(document: Document, declared: dict[str, list[str]]) -> list[str]:
    warnings: list[str] = []
    source = "\n".join(cell.source for cell in document.cells)
    network_hosts = {host.lower() for host in re.findall(r"https?://([^/:\s'\"]+)", source)}
    ssh_hosts = {
        host.lower()
        for host in re.findall(r"(?:^|[;&|\n])\s*ssh\s+(?:[^\s]+@)?([A-Za-z0-9][A-Za-z0-9.-]*)", source)
    }
    for host in sorted(network_hosts - set(declared.get("network", []))):
        warnings.append(f"warning: literal network host is not declared in capabilities.network: {host}")
    for host in sorted(ssh_hosts - set(declared.get("ssh", []))):
        warnings.append(f"warning: literal SSH host is not declared in capabilities.ssh: {host}")
    return warnings
