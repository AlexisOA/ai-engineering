from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.context.examples import CANONICAL_EXAMPLES
from app.services import llm_service

WELL_FORMED_MD = CANONICAL_EXAMPLES[0].estimation_markdown


def _fake_openai_response(
    *, estimation: str = WELL_FORMED_MD, finish_reason: str = "stop"
) -> dict:
    return {
        "estimation": estimation,
        "model": "gpt-4o-mini",
        "provider": "openai",
        "finish_reason": finish_reason,
        "usage": {"input_tokens": 1234, "output_tokens": 567, "total_tokens": 1801},
    }


@pytest.fixture
def call_log(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict]]:
    """Replace _call_openai with a recording fake. Returns the list of calls made."""
    calls: list[dict] = []

    def fake(messages: list[dict], model: str, max_tokens: int) -> dict:
        calls.append({"messages": messages, "model": model, "max_tokens": max_tokens})
        # Mirror the real wrapper's behavior: low max_tokens -> length finish_reason
        finish_reason = "length" if max_tokens <= 200 else "stop"
        return _fake_openai_response(finish_reason=finish_reason)

    monkeypatch.setattr(llm_service, "_call_openai", fake)
    yield calls


def test_default_request_returns_validation(client: TestClient, call_log: list[dict]) -> None:
    payload = {"transcription": "We need a small CRM with auth, contacts and roles. MVP six weeks."}
    response = client.post("/api/v1/estimate", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["preprocessing"] == "none"
    assert body["finish_reason"] == "stop"
    assert body["validation"] is not None
    assert body["validation"]["score"] == 1.0
    assert body["extracted_requirements"] is None
    assert len(call_log) == 1


def test_two_phase_invokes_llm_twice_and_fills_extracted(
    client: TestClient, call_log: list[dict]
) -> None:
    payload = {
        "transcription": "We need a small CRM with auth, contacts and roles. MVP six weeks.",
        "preprocessing": "two_phase",
    }
    response = client.post("/api/v1/estimate", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["preprocessing"] == "two_phase"
    assert body["extracted_requirements"] is not None
    assert len(call_log) == 2
    # The second call's user message should be the extracted requirements,
    # not the original transcription.
    second_user_msg = call_log[1]["messages"][-1]["content"]
    assert second_user_msg == body["extracted_requirements"]


def test_max_tokens_low_propagates_finish_reason_length(
    client: TestClient, call_log: list[dict]
) -> None:
    payload = {
        "transcription": "We need a small CRM with auth, contacts and roles. MVP six weeks.",
        "max_tokens": 200,
    }
    response = client.post("/api/v1/estimate", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["finish_reason"] == "length"
    assert body["validation"]["finish_reason_ok"] is False
    assert any("truncated" in m.lower() for m in body["validation"]["issues"])


def test_example_format_json_returns_200(client: TestClient, call_log: list[dict]) -> None:
    payload = {
        "transcription": "We need a small CRM with auth, contacts and roles. MVP six weeks.",
        "example_format": "json",
        "num_examples": 2,
    }
    response = client.post("/api/v1/estimate", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["usage"]["input_tokens"] > 0
    # The system message sent to OpenAI should contain the JSON examples block
    system_msg = call_log[0]["messages"][0]["content"]
    assert "Reference examples (JSON):" in system_msg


def test_model_override_is_passed_to_provider(
    client: TestClient, call_log: list[dict]
) -> None:
    payload = {
        "transcription": "We need a small CRM with auth, contacts and roles. MVP six weeks.",
        "model": "gpt-4o",
    }
    response = client.post("/api/v1/estimate", json=payload)
    assert response.status_code == 200
    assert call_log[0]["model"] == "gpt-4o"


def test_use_examples_false_omits_examples_block(
    client: TestClient, call_log: list[dict]
) -> None:
    payload = {
        "transcription": "We need a small CRM with auth, contacts and roles. MVP six weeks.",
        "use_examples": False,
    }
    response = client.post("/api/v1/estimate", json=payload)
    assert response.status_code == 200
    system_msg = call_log[0]["messages"][0]["content"]
    assert "EXAMPLE 1" not in system_msg
    assert "Reference examples" not in system_msg
