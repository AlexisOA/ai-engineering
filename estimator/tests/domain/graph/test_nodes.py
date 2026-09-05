"""Unit tests for the five graph nodes (Session 13) — LLM/backend mocked, no cost."""

from __future__ import annotations

from types import SimpleNamespace

from app.domain.graph import nodes as nodes_mod
from app.domain.graph.schemas import ComponentOut, ComponentsList, RequirementsList


class _FakeWrapper:
    def __init__(self, responses):
        self._responses = list(responses)

    def complete_structured(self, **kwargs):
        return self._responses.pop(0), {}


class _FailingWrapper:
    def complete_structured(self, **kwargs):
        raise RuntimeError("boom")


def _fake_settings():
    return SimpleNamespace(AGENT_MODEL="claude-haiku-4-5", AGENT_REASONING_EFFORT="medium")


async def test_extract_requirements_returns_requirements(monkeypatch):
    monkeypatch.setattr(nodes_mod, "get_settings", _fake_settings)
    monkeypatch.setattr(
        nodes_mod,
        "get_llm_wrapper",
        lambda: _FakeWrapper([RequirementsList(requirements=["r1", "r2"])]),
    )
    result = await nodes_mod.extract_requirements({"transcript": "..."})
    assert result == {"requirements": ["r1", "r2"]}


async def test_extract_requirements_handles_llm_failure(monkeypatch):
    monkeypatch.setattr(nodes_mod, "get_settings", _fake_settings)
    monkeypatch.setattr(nodes_mod, "get_llm_wrapper", lambda: _FailingWrapper())
    result = await nodes_mod.extract_requirements({"transcript": "..."})
    assert result["requirements"] == []
    assert "extract_requirements" in result["errors"][0]


async def test_classify_components_groups_requirements(monkeypatch):
    monkeypatch.setattr(nodes_mod, "get_settings", _fake_settings)
    monkeypatch.setattr(
        nodes_mod,
        "get_llm_wrapper",
        lambda: _FakeWrapper(
            [ComponentsList(components=[ComponentOut(name="Auth", category="backend")])]
        ),
    )
    result = await nodes_mod.classify_components({"requirements": ["OAuth login"]})
    assert result == {"components": [{"name": "Auth", "category": "backend"}]}


async def test_classify_components_short_circuits_with_no_requirements():
    result = await nodes_mod.classify_components({"requirements": []})
    assert result["components"] == []
    assert result["errors"]


async def test_search_budgets_node_is_sequential_and_collects_errors():
    async def backend(query, sectors):
        if query == "Bad":
            raise RuntimeError("db down")
        return [{"id": 1, "budget_id": "B1", "estimated_hours": 100.0}]

    node = nodes_mod.make_search_budgets_node(backend)
    state = {
        "components": [
            {"name": "Good", "category": "backend"},
            {"name": "Bad", "category": "mobile"},
        ]
    }
    result = await node(state)

    assert result["budget_matches"] == [
        {"component": "Good", "reference_budget_id": "B1", "amount": 100.0}
    ]
    assert "search_budgets(Bad)" in result["errors"][0]


async def test_generate_estimate_uses_median_and_flags_unbudgeted():
    state = {
        "components": [
            {"name": "Auth", "category": "backend"},
            {"name": "Ghost", "category": "mobile"},
        ],
        "budget_matches": [
            {"component": "Auth", "reference_budget_id": "b1", "amount": 400.0},
            {"component": "Auth", "reference_budget_id": "b2", "amount": 420.0},
        ],
    }
    result = await nodes_mod.generate_estimate(state)
    estimate = result["estimate"]

    auth = next(c for c in estimate["components"] if c["name"] == "Auth")
    assert auth["estimated_hours"] == 471.5  # median(400, 420) * 1.15
    ghost = next(c for c in estimate["components"] if c["name"] == "Ghost")
    assert ghost["unbudgeted"] is True
    assert estimate["total_hours"] == 471.5


async def test_validate_and_consolidate_flags_needs_review_on_unbudgeted():
    state = {
        "estimate": {
            "components": [{"name": "Ghost", "estimated_hours": 0.0, "unbudgeted": True}],
            "total_hours": 0.0,
        }
    }
    result = await nodes_mod.validate_and_consolidate(state)
    assert result["status"] == "needs_review"


async def test_validate_and_consolidate_passes_a_coherent_estimate():
    state = {
        "estimate": {
            "components": [{"name": "Auth", "estimated_hours": 460.0, "unbudgeted": False}],
            "total_hours": 460.0,
        }
    }
    result = await nodes_mod.validate_and_consolidate(state)
    assert result["status"] == "validated"
