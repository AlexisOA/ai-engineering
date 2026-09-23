"""API-key auth tests for the Session 9 routers.

Downstream work is stubbed so a request with a valid key reaches a 200; the
focus is the 401/200 boundary and the independence of the two keys.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.routers.estimate as estimate_router
import app.api.routers.retrieval as retrieval_router
import app.api.security as security
from app.dependencies import get_estimation_service
from app.domain.schemas.estimation import EstimationResponse, EstimationResult
from app.generation.rag.schemas import Estimate, RetrievalResult
from app.main import app

RET_KEY = "retrieval-secret"
EST_KEY = "estimate-secret"
SERVICE_TOKEN = "service-secret"  # nosec — test fixture, not a real credential


@pytest.fixture(autouse=True)
def stub(monkeypatch):
    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "RETRIEVAL_API_KEY": RET_KEY,
                "ESTIMATE_API_KEY": EST_KEY,
                "AI_SERVICE_TOKEN": SERVICE_TOKEN,
            },
        )(),
    )

    async def fake_retrieve(**kwargs):
        return RetrievalResult(chunks=[], low_confidence=True, candidates_evaluated=0)

    async def fake_estimate(transcript, idempotency_key=None):
        return Estimate(
            confidence="insufficient",
            reasoning="stub",
            insufficient_context_explanation="stub",
        )

    fake_runtime = type(
        "RT",
        (),
        {"effective_search_mode": lambda self: "vector", "effective_rerank": lambda self: False},
    )()
    monkeypatch.setattr(
        retrieval_router,
        "get_embedder",
        lambda: type("E", (), {"embed_one": staticmethod(lambda t: [0.0] * 1536)})(),
    )
    monkeypatch.setattr(retrieval_router, "get_runtime_retrieval_config", lambda: fake_runtime)
    monkeypatch.setattr(retrieval_router, "retrieve", fake_retrieve)
    monkeypatch.setattr(estimate_router, "estimate_from_transcript", fake_estimate)

    class _FakeEstimationService:
        def estimate(self, request):
            return EstimationResponse(
                result=EstimationResult(
                    summary="Stubbed estimation result for the security test.",
                    total_duration_weeks=1,
                    total_cost_eur=1000,
                    confidence_pct=50,
                    phases=[
                        {
                            "name": "Build",
                            "duration_weeks": 1,
                            "cost_eur": 1000,
                            "summary": "Stubbed single phase.",
                        }
                    ],
                ),
                prompt_version="v1",
                cached=False,
            )

    app.dependency_overrides[get_estimation_service] = lambda: _FakeEstimationService()
    yield
    app.dependency_overrides.pop(get_estimation_service, None)


@pytest.fixture
def client():
    return TestClient(app)


_SEARCH_BODY = {"query_text": "ecommerce storefront with card checkout"}
_ESTIMATE_BODY = {"transcript": "x" * 200}


def test_retrieval_requires_a_key(client):
    r = client.post("/v1/retrieval/search", json=_SEARCH_BODY)
    assert r.status_code == 401


def test_retrieval_accepts_its_own_key(client):
    r = client.post("/v1/retrieval/search", json=_SEARCH_BODY, headers={"X-API-Key": RET_KEY})
    assert r.status_code == 200


def test_estimate_requires_a_key(client):
    r = client.post("/v1/estimate/from-transcript", json=_ESTIMATE_BODY)
    assert r.status_code == 401


def test_estimate_accepts_its_own_key(client):
    r = client.post(
        "/v1/estimate/from-transcript", json=_ESTIMATE_BODY, headers={"X-API-Key": EST_KEY}
    )
    assert r.status_code == 200


def test_keys_are_independent(client):
    # The retrieval key must NOT open the estimate endpoint and vice versa.
    r1 = client.post(
        "/v1/estimate/from-transcript", json=_ESTIMATE_BODY, headers={"X-API-Key": RET_KEY}
    )
    r2 = client.post("/v1/retrieval/search", json=_SEARCH_BODY, headers={"X-API-Key": EST_KEY})
    assert r1.status_code == 401
    assert r2.status_code == 401


def test_wrong_key_is_rejected(client):
    r = client.post("/v1/retrieval/search", json=_SEARCH_BODY, headers={"X-API-Key": "nope"})
    assert r.status_code == 401


def test_response_carries_request_id_header(client):
    r = client.post("/v1/retrieval/search", json=_SEARCH_BODY, headers={"X-API-Key": RET_KEY})
    assert r.headers.get("X-Request-ID")


_ESTIMATION_BODY = {
    "description": "A small B2B SaaS to manage employee equipment loans across teams.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table",
}


def test_estimation_requires_a_service_token(client):
    r = client.post("/api/v1/estimate", json=_ESTIMATION_BODY)
    assert r.status_code == 401


def test_estimation_accepts_its_own_service_token(client):
    r = client.post(
        "/api/v1/estimate", json=_ESTIMATION_BODY, headers={"X-Service-Token": SERVICE_TOKEN}
    )
    assert r.status_code == 200


def test_estimation_rejects_a_wrong_service_token(client):
    r = client.post("/api/v1/estimate", json=_ESTIMATION_BODY, headers={"X-Service-Token": "nope"})
    assert r.status_code == 401


def test_estimation_rejects_an_unrelated_api_key(client):
    # The Session 9 X-API-Key must not double as the service token.
    r = client.post(
        "/api/v1/estimate", json=_ESTIMATION_BODY, headers={"X-Service-Token": EST_KEY}
    )
    assert r.status_code == 401
