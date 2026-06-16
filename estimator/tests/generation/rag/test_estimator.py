"""Flow tests for the end-to-end orchestrator (Session 9).

Every component is mocked: we validate the wiring (which stage runs, in what
order, and the soft-fail short-circuit), not the components themselves.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.dependencies as deps
from app.generation.rag import estimator as orch
from app.generation.rag.schemas import (
    Estimate,
    EstimationQuery,
    RetrievalResult,
    RetrievedChunk,
    SourceCitation,
)

_SETTINGS = SimpleNamespace(
    REFORMULATION_MODEL="gpt-5-mini",
    GENERATION_MODEL="gpt-5",
    GENERATION_REASONING_EFFORT="medium",
    RETRIEVAL_TOP_K=10,
    RETRIEVAL_DISTANCE_THRESHOLD=0.6,
    MAX_CONTEXT_TOKENS=100_000,
)


class CharEncoder:
    def encode(self, text: str) -> list[str]:
        return list(text)


class RecordingStore:
    def __init__(self):
        self.saved: dict[str, Estimate] = {}

    def get(self, key):
        return self.saved.get(key)

    def set(self, key, estimate):
        self.saved[key] = estimate


def _chunk(chunk_id: int) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        content="Component: Checkout\nEstimated hours: 140",
        sector="ecommerce",
        project_year=2024,
        chunk_type="budget_component",
        distance=0.42,
    )


def _good_estimate() -> Estimate:
    return Estimate(
        total_engineer_days=18,
        duration_weeks=4,
        cost_breakdown=[],
        sources=[SourceCitation(source_id=1, relevance="primary", used_for="checkout")],
        assumptions=[],
        confidence="high",
        reasoning="Grounded in BUD-2024-005.",
    )


@pytest.fixture
def wire(monkeypatch):
    """Wire the orchestrator with mocked stages; return a call counter."""
    calls = {"reformulate": 0, "search": 0, "generate": 0, "embed": 0}
    store = RecordingStore()

    def _wire(*, retrieval: RetrievalResult, estimate: Estimate | None = None):
        async def fake_reformulate(transcript):
            calls["reformulate"] += 1
            return EstimationQuery(function="ecommerce storefront", sector="ecommerce")

        async def fake_search(query_embedding, **kwargs):
            calls["search"] += 1
            return retrieval

        async def fake_generate(context_block, structured_query):
            calls["generate"] += 1
            return estimate

        def fake_embed(text):
            calls["embed"] += 1
            return [0.0] * 1536

        monkeypatch.setattr(orch, "get_settings", lambda: _SETTINGS)
        monkeypatch.setattr(orch, "reformulate_query", fake_reformulate)
        monkeypatch.setattr(orch, "search_chunks", fake_search)
        monkeypatch.setattr(orch, "generate_estimate", fake_generate)
        monkeypatch.setattr(deps, "get_embedder", lambda: SimpleNamespace(embed_one=fake_embed))
        monkeypatch.setattr(deps, "get_token_encoder", lambda: CharEncoder())
        monkeypatch.setattr(deps, "get_idempotency_store", lambda: store)
        return calls, store

    return _wire


async def test_happy_path_runs_all_stages(wire):
    retrieval = RetrievalResult(chunks=[_chunk(1)], low_confidence=False, candidates_evaluated=5)
    calls, _store = wire(retrieval=retrieval, estimate=_good_estimate())

    result = await orch.estimate_from_transcript("x" * 200)

    assert result.confidence == "high"
    assert result.total_engineer_days == 18
    assert calls == {"reformulate": 1, "search": 1, "generate": 1, "embed": 1}


async def test_soft_fail_skips_generation(wire):
    retrieval = RetrievalResult(chunks=[], low_confidence=True, candidates_evaluated=7)
    calls, _store = wire(retrieval=retrieval, estimate=_good_estimate())

    result = await orch.estimate_from_transcript("x" * 200)

    assert result.confidence == "insufficient"
    assert result.total_engineer_days is None
    assert result.insufficient_context_explanation
    assert calls["generate"] == 0  # generator never called on soft-fail


async def test_idempotency_hit_short_circuits_pipeline(wire):
    retrieval = RetrievalResult(chunks=[_chunk(1)], low_confidence=False, candidates_evaluated=5)
    calls, store = wire(retrieval=retrieval, estimate=_good_estimate())

    first = await orch.estimate_from_transcript("x" * 200, idempotency_key="k1")
    assert calls["generate"] == 1
    assert store.saved.get("k1") is not None

    second = await orch.estimate_from_transcript("x" * 200, idempotency_key="k1")
    assert second == first
    # No stage re-ran on the cached call.
    assert calls == {"reformulate": 1, "search": 1, "generate": 1, "embed": 1}
