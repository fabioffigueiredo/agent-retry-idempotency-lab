import json
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

from http.server import ThreadingHTTPServer

from agent_retry_lab.web import PAGE, RetryDemoApplication, make_handler


def test_page_exposes_recording_controls_and_mobile_viewport() -> None:
    assert 'name="viewport"' in PAGE
    assert 'data-testid="run-naive"' in PAGE
    assert 'data-testid="run-idempotent"' in PAGE
    assert 'data-testid="run-conflict"' in PAGE
    assert "Sequência ilustrada" in PAGE
    assert "Resultado consultado no SQLite" in PAGE
    assert "POST /tickets" not in PAGE
    assert "window.demoReady=true" in PAGE


def test_naive_response_matches_durable_effect_rows(tmp_path: Path) -> None:
    application = RetryDemoApplication(tmp_path / "demo.sqlite")
    payload = application.scenario("naive")

    assert payload["summary"]["attempts"] == 2
    assert payload["summary"]["effect_count"] == 2
    assert len(payload["effects"]) == 2
    assert {row["operation_id"] for row in payload["effects"]} == {
        "ticket-demo-001"
    }


def test_idempotent_response_matches_single_durable_effect(tmp_path: Path) -> None:
    application = RetryDemoApplication(tmp_path / "demo.sqlite")
    payload = application.scenario("idempotent")

    assert payload["summary"]["attempts"] == 2
    assert payload["summary"]["effect_count"] == 1
    assert payload["summary"]["replayed"] is True
    assert len(payload["effects"]) == 1


def test_conflicting_payload_is_rejected_without_second_effect(tmp_path: Path) -> None:
    application = RetryDemoApplication(tmp_path / "demo.sqlite")
    payload = application.scenario("conflict")

    assert payload["summary"]["status"] == "payload_conflict"
    assert payload["summary"]["attempts_label"] == "Tentativas divergentes"
    assert payload["summary"]["effect_count"] == 1
    assert len(payload["effects"]) == 1
    json.dumps(payload)


def test_each_scenario_starts_from_a_clean_database(tmp_path: Path) -> None:
    application = RetryDemoApplication(tmp_path / "demo.sqlite")
    assert application.scenario("naive")["summary"]["effect_count"] == 2
    assert application.scenario("idempotent")["summary"]["effect_count"] == 1
    assert application.state()["effect_count"] == 1


def test_http_api_returns_the_rows_persisted_in_sqlite(tmp_path: Path) -> None:
    application = RetryDemoApplication(tmp_path / "demo.sqlite")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(application))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/scenarios/idempotent",
            method="POST",
        )
        with urlopen(request) as response:  # noqa: S310 - loopback test server
            payload = json.load(response)
        assert payload["summary"]["effect_count"] == 1
        assert len(payload["effects"]) == application.state()["effect_count"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
