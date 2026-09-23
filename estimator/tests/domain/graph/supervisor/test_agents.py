"""Each specialist agent in isolation — network-free, minimum privilege honoured."""

from __future__ import annotations

import pytest

from app.domain.graph.schemas import ComponentClassification, RequirementsExtraction
from app.domain.graph.supervisor.agents import (
    budget_searcher,
    coherence_validator,
    estimate_generator,
    requirements_extractor,
)


class _FakeWrapper:
    def __init__(self, *, requirements=None, components=None):
        self._requirements = requirements or []
        self._components = components or []

    def complete_structured(self, *, response_model, **kwargs):
        meta = {"model": "fake", "provider": "fake", "latency_ms": 1}
        if response_model is RequirementsExtraction:
            return RequirementsExtraction(requirements=self._requirements), meta
        if response_model is ComponentClassification:
            return ComponentClassification(components=self._components), meta
        raise AssertionError(f"unexpected response_model {response_model!r}")


@pytest.mark.asyncio
async def test_requirements_extractor_uses_no_tool(monkeypatch):
    monkeypatch.setattr(
        "app.dependencies.get_llm_wrapper",
        lambda: _FakeWrapper(requirements=["OAuth2 login", "Admin dashboard"]),
    )

    update = await requirements_extractor({"transcript": "..."})

    assert update["requirements"] == ["OAuth2 login", "Admin dashboard"]
    [contribution] = update["agent_contributions"]
    assert contribution["agent"] == "requirements_extractor"
    assert contribution["tool"] is None
    assert contribution["outcome"] == "ok"


@pytest.mark.asyncio
async def test_budget_searcher_only_calls_search_budgets(monkeypatch):
    from app.domain.graph.schemas import ComponentModel

    monkeypatch.setattr(
        "app.dependencies.get_llm_wrapper",
        lambda: _FakeWrapper(components=[ComponentModel(name="Backend API", category="backend")]),
    )

    async def fake_backend(query, sectors):
        return [
            {"estimated_hours": 80, "distance": 0.1, "budget_id": "B1"},
            {"estimated_hours": 100, "distance": 0.3, "budget_id": "B2"},
        ]

    monkeypatch.setattr(
        "app.domain.graph.supervisor.agents.make_retrieval_backend",
        lambda **kwargs: fake_backend,
    )

    update = await budget_searcher({"requirements": ["Build a backend API"]})

    assert update["components"] == [{"name": "Backend API", "category": "backend"}]
    assert len(update["budget_matches"]) == 2
    assert {m["amount"] for m in update["budget_matches"]} == {80.0, 100.0}
    [contribution] = update["agent_contributions"]
    assert contribution["tool"] == "search_budgets"
    assert contribution["outcome"] == "ok"


@pytest.mark.asyncio
async def test_estimate_generator_is_deterministic_no_llm():
    state = {
        "components": [{"name": "Backend API", "category": "backend"}],
        "budget_matches": [
            {
                "component": "Backend API",
                "reference_budget_id": "B1",
                "amount": 80.0,
                "distance": 0.1,
            },
            {
                "component": "Backend API",
                "reference_budget_id": "B2",
                "amount": 88.0,
                "distance": 0.2,
            },
        ],
    }

    update = await estimate_generator(state)

    assert update["estimate"]["components"][0]["name"] == "Backend API"
    assert update["estimate"]["components"][0]["engineer_days"] is not None
    assert update["estimate"]["total_engineer_days"] > 0
    assert 0.0 <= update["confidence"] <= 1.0
    [contribution] = update["agent_contributions"]
    assert contribution["tool"] == "derive_task_hours"


@pytest.mark.asyncio
async def test_estimate_generator_leaves_unmatched_component_ungrounded():
    state = {
        "components": [{"name": "Legacy COBOL bridge", "category": "integration"}],
        "budget_matches": [],
    }

    update = await estimate_generator(state)

    assert update["estimate"]["components"][0]["engineer_days"] is None
    assert update["estimate"]["total_engineer_days"] == 0
    assert update["confidence"] == 0.0


@pytest.mark.asyncio
async def test_coherence_validator_flags_missing_reference():
    state = {
        "estimate": {
            "components": [{"name": "Legacy COBOL bridge", "engineer_days": None}],
            "total_engineer_days": 0,
        },
        "budget_matches": [],
    }

    update = await coherence_validator(state)

    assert update["status"] == "needs_review"
    assert update["validation"]["ok"] is False
    assert update["validation"]["issues"]
    [contribution] = update["agent_contributions"]
    assert contribution["tool"] == "validate_estimate"


@pytest.mark.asyncio
async def test_coherence_validator_passes_a_clean_estimate():
    state = {
        "estimate": {
            "components": [{"name": "Backend API", "engineer_days": 10}],
            "total_engineer_days": 10,
        },
        "budget_matches": [
            {
                "component": "Backend API",
                "reference_budget_id": "B1",
                "amount": 80.0,
                "distance": 0.1,
            },
        ],
    }

    update = await coherence_validator(state)

    assert update["status"] == "validated"
    assert update["validation"]["ok"] is True
