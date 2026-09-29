from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest

from agent_retry_lab import InvalidPayloadError, PayloadConflictError, run_operation


def test_naive_retry_duplicates_the_committed_effect(tmp_path: Path) -> None:
    result = run_operation(
        tmp_path / "lab.sqlite",
        operation_id="ticket-naive-001",
        payload={"action": "open", "ticket": "TCK-001"},
        mode="naive",
    )

    assert result == {
        "scenario": "naive",
        "operation_id": "ticket-naive-001",
        "attempts": 2,
        "effect_count": 2,
        "replayed": False,
        "status": "completed",
        "payload_sha256": "18721fa4ae59d9ca60332cb83c065eeff291aa1f6ac139778ab7013b41ab6fae",
    }


def test_idempotent_retry_keeps_single_committed_effect(tmp_path: Path) -> None:
    result = run_operation(
        tmp_path / "lab.sqlite",
        operation_id="ticket-idempotent-001",
        payload={"action": "open", "ticket": "TCK-001"},
        mode="idempotent",
    )

    assert result == {
        "scenario": "idempotent",
        "operation_id": "ticket-idempotent-001",
        "attempts": 2,
        "effect_count": 1,
        "replayed": True,
        "status": "completed",
        "payload_sha256": "18721fa4ae59d9ca60332cb83c065eeff291aa1f6ac139778ab7013b41ab6fae",
    }


def test_reusing_a_key_with_a_different_payload_fails_without_a_new_effect(
    tmp_path: Path,
) -> None:
    database = tmp_path / "lab.sqlite"
    run_operation(
        database,
        operation_id="stable-key-001",
        payload={"amount": 10},
        mode="idempotent",
    )

    with pytest.raises(
        PayloadConflictError,
        match="operation_id 'stable-key-001' was already used with another payload",
    ):
        run_operation(
            database,
            operation_id="stable-key-001",
            payload={"amount": 11},
            mode="idempotent",
        )

    replay = run_operation(
        database,
        operation_id="stable-key-001",
        payload={"amount": 10},
        mode="idempotent",
    )
    assert replay["effect_count"] == 1


def test_concurrent_calls_with_the_same_key_create_exactly_one_effect(
    tmp_path: Path,
) -> None:
    database = tmp_path / "lab.sqlite"
    start = Barrier(2)

    def invoke() -> dict[str, object]:
        start.wait()
        return run_operation(
            database,
            operation_id="concurrent-key-001",
            payload={"action": "reserve", "item": "fictitious-item"},
            mode="idempotent",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: invoke(), range(2)))

    assert {result["effect_count"] for result in results} == {1}
    assert sorted(result["attempts"] for result in results) == [1, 2]
    assert all(result["replayed"] is True for result in results)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({1: "x"}, "JSON object keys must be strings"),
        ({"value": float("nan")}, "JSON numbers must be finite"),
        ({"value": float("inf")}, "JSON numbers must be finite"),
        (("not", "a", "JSON array"), "unsupported JSON value type: tuple"),
    ],
)
def test_invalid_json_payload_is_rejected_before_it_can_create_an_effect(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    database = tmp_path / "lab.sqlite"

    with pytest.raises(InvalidPayloadError, match=message):
        run_operation(
            database,
            operation_id="validated-key-001",
            payload=payload,
            mode="idempotent",
        )

    valid = run_operation(
        database,
        operation_id="validated-key-001",
        payload={"1": "x"},
        mode="idempotent",
    )
    assert valid["effect_count"] == 1


def test_failed_key_insert_rolls_back_effect_in_same_transaction(
    tmp_path: Path,
) -> None:
    database = tmp_path / "lab.sqlite"
    run_operation(
        database,
        operation_id="seed-001",
        payload={"action": "seed"},
        mode="idempotent",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_test_key BEFORE INSERT ON operation_keys
            WHEN NEW.operation_id = 'rollback-001'
            BEGIN
                SELECT RAISE(ABORT, 'injected key write failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected key write failure"):
        run_operation(
            database,
            operation_id="rollback-001",
            payload={"action": "open", "ticket": "TCK-ROLLBACK"},
            mode="idempotent",
        )

    with sqlite3.connect(database) as connection:
        effects = connection.execute(
            "SELECT COUNT(*) FROM effects WHERE operation_id = 'rollback-001'"
        ).fetchone()[0]
        keys = connection.execute(
            "SELECT COUNT(*) FROM operation_keys WHERE operation_id = 'rollback-001'"
        ).fetchone()[0]
    assert (effects, keys) == (0, 0)
