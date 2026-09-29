"""Deterministic artifact generation for the local demonstration."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from . import PayloadConflictError, _payload_digest, run_operation

RESULT_FIELDS = (
    "scenario",
    "operation_id",
    "attempts",
    "effect_count",
    "replayed",
    "status",
    "payload_sha256",
)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_summary(path: Path, results: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=RESULT_FIELDS, lineterminator="\n")
        writer.writeheader()
        for result in results:
            row = dict(result)
            row["replayed"] = json.dumps(row["replayed"])
            writer.writerow(row)


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_demo(output_dir: str | Path) -> None:
    """Generate the three scenarios plus summary and integrity manifest."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="agent-retry-lab-") as temporary:
        database = Path(temporary) / "demo.sqlite"
        base_payload = {"action": "open", "ticket": "TCK-DEMO-001"}
        naive = run_operation(
            database,
            operation_id="demo-naive-001",
            payload=base_payload,
            mode="naive",
        )
        idempotent = run_operation(
            database,
            operation_id="demo-idempotent-001",
            payload=base_payload,
            mode="idempotent",
        )

        conflict_operation_id = "demo-conflict-001"
        original_payload = {"amount": 10, "currency": "FIC"}
        conflicting_payload = {"amount": 11, "currency": "FIC"}
        original = run_operation(
            database,
            operation_id=conflict_operation_id,
            payload=original_payload,
            mode="idempotent",
        )
        try:
            run_operation(
                database,
                operation_id=conflict_operation_id,
                payload=conflicting_payload,
                mode="idempotent",
            )
        except PayloadConflictError:
            conflict = {
                "scenario": "payload-conflict",
                "operation_id": conflict_operation_id,
                "attempts": 1,
                "effect_count": original["effect_count"],
                "replayed": False,
                "status": "payload_conflict",
                "payload_sha256": _payload_digest(conflicting_payload),
            }
        else:  # pragma: no cover - protects the demonstration contract
            raise RuntimeError("the conflicting payload was unexpectedly accepted")

    results = [naive, idempotent, conflict]
    filenames = ("naive.json", "idempotent.json", "payload-conflict.json")
    for filename, result in zip(filenames, results, strict=True):
        _write_json(destination / filename, result)

    _write_summary(destination / "summary.csv", results)
    result_files = (*filenames, "summary.csv")
    manifest = {
        "algorithm": "sha256",
        "files": {
            filename: _file_digest(destination / filename)
            for filename in result_files
        },
    }
    _write_json(destination / "manifest.json", manifest)
