import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


RESULT_FIELDS = {
    "scenario",
    "operation_id",
    "attempts",
    "effect_count",
    "replayed",
    "status",
    "payload_sha256",
}


def test_demo_writes_scenarios_summary_and_verified_manifest(tmp_path: Path) -> None:
    output_dir = tmp_path / "demo"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "src"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_retry_lab",
            "demo",
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert {path.name for path in output_dir.iterdir()} == {
        "naive.json",
        "idempotent.json",
        "payload-conflict.json",
        "summary.csv",
        "manifest.json",
    }

    scenarios = {
        name: json.loads((output_dir / name).read_text(encoding="utf-8"))
        for name in ("naive.json", "idempotent.json", "payload-conflict.json")
    }
    assert all(set(result) == RESULT_FIELDS for result in scenarios.values())
    assert scenarios["naive.json"]["effect_count"] == 2
    assert scenarios["naive.json"]["replayed"] is False
    assert scenarios["idempotent.json"]["effect_count"] == 1
    assert scenarios["idempotent.json"]["replayed"] is True
    assert scenarios["payload-conflict.json"]["status"] == "payload_conflict"
    assert scenarios["payload-conflict.json"]["effect_count"] == 1

    with (output_dir / "summary.csv").open(encoding="utf-8", newline="") as stream:
        summary = list(csv.DictReader(stream))
    assert [row["scenario"] for row in summary] == [
        "naive",
        "idempotent",
        "payload-conflict",
    ]

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["algorithm"] == "sha256"
    assert set(manifest["files"]) == {
        "naive.json",
        "idempotent.json",
        "payload-conflict.json",
        "summary.csv",
    }
    for filename, recorded_digest in manifest["files"].items():
        actual_digest = hashlib.sha256((output_dir / filename).read_bytes()).hexdigest()
        assert recorded_digest == actual_digest


def test_demo_outputs_are_byte_for_byte_deterministic(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "src"
    output_dirs = [tmp_path / "first", tmp_path / "second"]

    for output_dir in output_dirs:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_retry_lab",
                "demo",
                "--output-dir",
                str(output_dir),
            ],
            cwd=Path(__file__).parents[1],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )

    first_files = {
        path.name: path.read_bytes() for path in output_dirs[0].iterdir()
    }
    second_files = {
        path.name: path.read_bytes() for path in output_dirs[1].iterdir()
    }
    assert first_files == second_files
