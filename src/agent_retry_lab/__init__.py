"""Public interface for the retry and idempotency laboratory."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Literal

Mode = Literal["naive", "idempotent"]


class PayloadConflictError(ValueError):
    """Raised when an idempotency key is reused for another payload."""


class InvalidPayloadError(ValueError):
    """Raised when a payload cannot be represented as unambiguous JSON."""


class _SimulatedTimeout(TimeoutError):
    """Represents a response lost after the database commit."""


def _validate_json_payload(value: Any, active_containers: set[int] | None = None) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidPayloadError("JSON numbers must be finite")
        return
    if not isinstance(value, (list, dict)):
        raise InvalidPayloadError(
            f"unsupported JSON value type: {type(value).__name__}"
        )

    active = active_containers if active_containers is not None else set()
    container_id = id(value)
    if container_id in active:
        raise InvalidPayloadError("JSON payload must not contain cycles")
    active.add(container_id)
    try:
        if isinstance(value, list):
            for item in value:
                _validate_json_payload(item, active)
            return

        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidPayloadError("JSON object keys must be strings")
            _validate_json_payload(item, active)
    finally:
        active.remove(container_id)


def _payload_digest(payload: Any) -> str:
    _validate_json_payload(payload)
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS effects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS operation_keys (
            operation_id TEXT PRIMARY KEY,
            payload_sha256 TEXT NOT NULL,
            effect_id INTEGER NOT NULL UNIQUE REFERENCES effects(id)
        )
        """
    )
    connection.commit()


def _apply_idempotent(
    connection: sqlite3.Connection,
    operation_id: str,
    digest: str,
    *,
    simulate_timeout: bool,
) -> bool:
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute(
        "SELECT payload_sha256 FROM operation_keys WHERE operation_id = ?",
        (operation_id,),
    ).fetchone()
    if row is not None:
        if row[0] != digest:
            connection.rollback()
            raise PayloadConflictError(
                f"operation_id {operation_id!r} was already used with another payload"
            )
        connection.commit()
        return True

    cursor = connection.execute(
        "INSERT INTO effects (operation_id, payload_sha256) VALUES (?, ?)",
        (operation_id, digest),
    )
    connection.execute(
        """
        INSERT INTO operation_keys (operation_id, payload_sha256, effect_id)
        VALUES (?, ?, ?)
        """,
        (operation_id, digest, cursor.lastrowid),
    )
    connection.commit()
    if simulate_timeout:
        raise _SimulatedTimeout("response lost after commit")
    return False


def run_operation(
    database: str | Path,
    *,
    operation_id: str,
    payload: Any,
    mode: Mode,
) -> dict[str, object]:
    """Run one fictitious operation including its automatic retry."""

    if mode not in ("naive", "idempotent"):
        raise ValueError(f"unsupported mode: {mode}")

    digest = _payload_digest(payload)
    with sqlite3.connect(database) as connection:
        _initialize(connection)
        replayed = False
        attempts = 0
        for attempt in (1, 2):
            attempts = attempt
            try:
                if mode == "idempotent":
                    replayed = _apply_idempotent(
                        connection,
                        operation_id,
                        digest,
                        simulate_timeout=attempt == 1,
                    )
                    break
                connection.execute(
                    "INSERT INTO effects (operation_id, payload_sha256) VALUES (?, ?)",
                    (operation_id, digest),
                )
                connection.commit()
                if attempt == 1:
                    raise _SimulatedTimeout("response lost after commit")
            except _SimulatedTimeout:
                continue

        effect_count = connection.execute(
            "SELECT COUNT(*) FROM effects WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()[0]

    return {
        "scenario": mode,
        "operation_id": operation_id,
        "attempts": attempts,
        "effect_count": effect_count,
        "replayed": replayed,
        "status": "completed",
        "payload_sha256": digest,
    }


def list_effects(
    database: str | Path,
    *,
    operation_id: str | None = None,
) -> list[dict[str, object]]:
    """Return the durable effects currently stored by the laboratory."""

    with sqlite3.connect(database) as connection:
        _initialize(connection)
        if operation_id is None:
            rows = connection.execute(
                "SELECT id, operation_id, payload_sha256 FROM effects ORDER BY id"
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, operation_id, payload_sha256
                FROM effects
                WHERE operation_id = ?
                ORDER BY id
                """,
                (operation_id,),
            ).fetchall()
    return [
        {
            "id": row[0],
            "operation_id": row[1],
            "payload_sha256": row[2],
        }
        for row in rows
    ]


__all__ = [
    "InvalidPayloadError",
    "Mode",
    "PayloadConflictError",
    "list_effects",
    "run_operation",
]
