"""End-to-end tests for POST /api/v1/estimate.

The LLM is mocked via FastAPI's ``dependency_overrides`` mechanism: the test
swaps the real ``LLMWrapper`` for a fake whose ``complete`` records the
arguments it received and returns a canned dict. This isolates the endpoint
from network access while still exercising request validation, prompt
rendering and response shaping.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_llm_wrapper
from app.main import app


class FakeWrapper:
    """Records the kwargs of every ``complete`` call and returns a canned dict."""

    def __init__(self, response_text: str = "fake estimation") -> None:
        self.response_text = response_text
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "estimation": self.response_text,
            "model": "gpt-4o-mini",
            "provider": "openai",
            "finish_reason": "stop",
            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            "latency_ms": 1,
            "cost_usd": 0.0,
            "cache_hit": False,
        }


@pytest.fixture
def fake_wrapper() -> FakeWrapper:
    wrapper = FakeWrapper()
    app.dependency_overrides[get_llm_wrapper] = lambda: wrapper
    yield wrapper
    app.dependency_overrides.pop(get_llm_wrapper, None)


VALID_PAYLOAD = {
    "description": "A small B2B SaaS to manage employee equipment loans across teams.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table",
}


def test_valid_payload_returns_text_and_prompt_version(
    client: TestClient, fake_wrapper: FakeWrapper
) -> None:
    response = client.post("/api/v1/estimate", json=VALID_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "fake estimation"
    assert body["prompt_version"] == "v1"


def test_endpoint_passes_separate_system_and_user_messages(
    client: TestClient, fake_wrapper: FakeWrapper
) -> None:
    client.post("/api/v1/estimate", json=VALID_PAYLOAD)
    assert len(fake_wrapper.calls) == 1
    call = fake_wrapper.calls[0]
    assert "system_prompt" in call
    assert "user_message" in call
    # Description must land inside the user message, not concatenated into system.
    assert VALID_PAYLOAD["description"] in call["user_message"]
    assert VALID_PAYLOAD["description"] not in call["system_prompt"]
    # The system prompt carries the role and the rules; the user prompt is short.
    assert "senior project estimator" in call["system_prompt"].lower()
    assert len(call["user_message"]) < len(call["system_prompt"])


def test_missing_project_type_returns_422(client: TestClient, fake_wrapper: FakeWrapper) -> None:
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "project_type"}
    response = client.post("/api/v1/estimate", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(err["loc"][-1] == "project_type" for err in detail)


def test_invalid_enum_value_returns_422(client: TestClient, fake_wrapper: FakeWrapper) -> None:
    payload = {**VALID_PAYLOAD, "project_type": "not_a_real_enum"}
    response = client.post("/api/v1/estimate", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(err["loc"][-1] == "project_type" for err in detail)


def test_short_description_returns_422(client: TestClient, fake_wrapper: FakeWrapper) -> None:
    payload = {**VALID_PAYLOAD, "description": "too short"}
    response = client.post("/api/v1/estimate", json=payload)
    assert response.status_code == 422
