"""End-to-end supervisor graph runs, network-free: the human gate pauses and resumes."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.domain.graph.schemas import ComponentClassification, ComponentModel, RequirementsExtraction
from app.domain.graph.supervisor.build import build_supervisor_graph

TRANSCRIPT = "A" * 200
CONFIG = {"configurable": {"thread_id": "t1"}}


class _FakeWrapper:
    def __init__(self):
        self.calls: list[str] = []

    def complete_structured(self, *, response_model, **kwargs):
        self.calls.append(response_model.__name__)
        meta = {"model": "fake", "provider": "fake", "latency_ms": 1}
        if response_model is RequirementsExtraction:
            return (
                RequirementsExtraction(requirements=["OAuth2 login", "QKD encrypted link"]),
                meta,
            )
        if response_model is ComponentClassification:
            return (
                ComponentClassification(
                    components=[
                        ComponentModel(name="Backend API", category="backend"),
                        ComponentModel(name="QKD integration", category="integration"),
                    ]
                ),
                meta,
            )
        raise AssertionError(f"unexpected response_model {response_model!r}")


def _wire(monkeypatch, *, wrapper, backend):
    monkeypatch.setattr("app.dependencies.get_llm_wrapper", lambda: wrapper)
    monkeypatch.setattr(
        "app.domain.graph.supervisor.agents.make_retrieval_backend", lambda **kwargs: backend
    )


@pytest.mark.asyncio
async def test_no_precedent_component_triggers_the_gate_and_resumes(monkeypatch):
    """One component has historical matches, the other (QKD — no precedent) has none:
    the gate must trigger, pause, persist, and resume cleanly with no duplicate audit row."""

    async def backend(query, sectors):
        if "QKD" in query:
            return []  # no historical precedent
        return [{"estimated_hours": 80, "distance": 0.1, "budget_id": "B1"}]

    wrapper = _FakeWrapper()
    _wire(monkeypatch, wrapper=wrapper, backend=backend)
    graph = build_supervisor_graph(MemorySaver())

    await graph.ainvoke({"transcript": TRANSCRIPT}, CONFIG)
    snap = await graph.aget_state(CONFIG)
    assert snap.next == ("human_review_gate",)
    assert snap.interrupts[0].value["gate"] == "low_confidence_estimate"
    assert "QKD" in snap.interrupts[0].value["reason"]
    # The 4 specialists each contributed exactly once before the pause.
    agents_seen = [c["agent"] for c in snap.values["agent_contributions"]]
    assert agents_seen.count("requirements_extractor") == 1
    assert agents_seen.count("coherence_validator") == 1

    result = await graph.ainvoke(Command(resume={"approved": True, "status": "validated"}), CONFIG)
    snap = await graph.aget_state(CONFIG)

    assert snap.next == ()  # completed
    assert result["status"] == "validated"
    assert result["human_decision"] == {"approved": True, "status": "validated"}
    # The gate's own audit row appears exactly once (no duplicate from the interrupt's re-entry).
    gate_rows = [c for c in snap.values["agent_contributions"] if c["agent"] == "human_review_gate"]
    assert len(gate_rows) == 1


@pytest.mark.asyncio
async def test_confident_estimate_skips_the_gate(monkeypatch):
    """Both components ground well and the estimate validates clean: no pause, straight to END."""

    async def backend(query, sectors):
        return [
            {"estimated_hours": 80, "distance": 0.05, "budget_id": "B1"},
            {"estimated_hours": 85, "distance": 0.08, "budget_id": "B2"},
        ]

    wrapper = _FakeWrapper()
    _wire(monkeypatch, wrapper=wrapper, backend=backend)
    graph = build_supervisor_graph(MemorySaver())

    result = await graph.ainvoke({"transcript": TRANSCRIPT}, CONFIG)
    snap = await graph.aget_state(CONFIG)

    assert snap.next == ()  # never paused
    assert result["status"] == "validated"
    assert result["confidence"] >= 0.6
    assert not any(
        c["agent"] == "human_review_gate" and c.get("tool") for c in result["agent_contributions"]
    )
