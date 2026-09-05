"""The compiled graph runs the five nodes in order and produces a status."""

from __future__ import annotations

from types import SimpleNamespace

from app.domain.graph import nodes as nodes_mod
from app.domain.graph.build import build_graph
from app.domain.graph.schemas import ComponentOut, ComponentsList, RequirementsList


class _ScriptedWrapper:
    """Returns extract_requirements' response first, then classify_components'."""

    def __init__(self, requirements, components):
        self._queue = [
            RequirementsList(requirements=requirements),
            ComponentsList(components=components),
        ]

    def complete_structured(self, **kwargs):
        return self._queue.pop(0), {}


async def _fake_backend(query: str, sectors) -> list[dict]:
    return [{"id": 1, "budget_id": "BUD-1", "estimated_hours": 400.0}]


def _patch_llm(monkeypatch, requirements, components):
    # One shared instance: extract_requirements and classify_components each
    # call get_llm_wrapper() independently and must pop from the SAME queue.
    wrapper = _ScriptedWrapper(requirements, components)
    monkeypatch.setattr(
        nodes_mod,
        "get_settings",
        lambda: SimpleNamespace(AGENT_MODEL="claude-haiku-4-5", AGENT_REASONING_EFFORT="medium"),
    )
    monkeypatch.setattr(nodes_mod, "get_llm_wrapper", lambda: wrapper)


async def test_graph_runs_end_to_end_and_validates(monkeypatch):
    _patch_llm(
        monkeypatch,
        requirements=["OAuth2 login with JWT"],
        components=[ComponentOut(name="Auth backend", category="backend")],
    )
    graph = build_graph(retrieval_backend=_fake_backend)

    result = await graph.ainvoke({"transcript": "a fintech needs an auth backend"})

    assert result["requirements"] == ["OAuth2 login with JWT"]
    assert result["components"] == [{"name": "Auth backend", "category": "backend"}]
    assert len(result["budget_matches"]) == 1
    assert result["estimate"]["total_hours"] > 0
    assert result["status"] == "validated"


async def test_graph_flags_needs_review_when_a_component_has_no_match(monkeypatch):
    _patch_llm(
        monkeypatch,
        requirements=["Something with no historical analog"],
        components=[ComponentOut(name="Exotic thing", category="unknown")],
    )

    async def _empty_backend(query: str, sectors) -> list[dict]:
        return []

    graph = build_graph(retrieval_backend=_empty_backend)
    result = await graph.ainvoke({"transcript": "..."})

    assert result["status"] == "needs_review"
