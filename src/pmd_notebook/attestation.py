from __future__ import annotations

from pathlib import Path
from typing import Any


def provenance_statement(document: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    revision = receipt.get("document_revision", "")
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": document.name, "digest": {"sha256": revision.removeprefix("sha256:")}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://polyglot-pmd.dev/verification/v0.1",
                "externalParameters": {
                    "plan_id": receipt.get("plan_id"),
                    "inputs": receipt.get("inputs", []),
                },
                "resolvedDependencies": receipt.get("inputs", []),
            },
            "runDetails": {
                "builder": {"id": "https://polyglot-pmd.dev", "version": receipt.get("runner", {})},
                "metadata": {
                    "invocationId": receipt.get("receipt_id"),
                    "startedOn": receipt.get("started_at"),
                    "finishedOn": receipt.get("finished_at"),
                },
            },
            "pmd": {
                "receipt_id": receipt.get("receipt_id"),
                "cells": receipt.get("cells", []),
                "tests": receipt.get("tests", []),
                "unsigned": True,
            },
        },
    }
