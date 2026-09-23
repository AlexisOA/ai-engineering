"""The compiled graph accepts the real edge-case delivery transcript end to end."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.domain.graph.schemas import ComponentClassification, ComponentModel, RequirementsExtraction
from app.domain.graph.supervisor.build import build_supervisor_graph

TRANSCRIPT_PATH = (
    Path(__file__).resolve().parents[4]
    / "exercises"
    / "session-14"
    / "sample_transcript_edge_case.txt"
)
CONFIG = {"configurable": {"thread_id": "edge-case"}}


class _FakeWrapper:
    def complete_structured(self, *, response_model, **kwargs):
        meta = {"model": "fake", "provider": "fake", "latency_ms": 1}
        if response_model is RequirementsExtraction:
            return (
                RequirementsExtraction(
                    requirements=["QKD-encrypted telemetry link", "COBOL mainframe file exchange"]
                ),
                meta,
            )
        if response_model is ComponentClassification:
            return (
                ComponentClassification(
                    components=[
                        ComponentModel(name="QKD telemetry link", category="integration"),
                        ComponentModel(name="COBOL mainframe bridge", category="integration"),
                    ]
                ),
                meta,
            )
        raise AssertionError(f"unexpected response_model {response_model!r}")


@pytest.mark.asyncio
async def test_edge_case_transcript_pauses_for_human_review(monkeypatch):
    """Both components in this transcript are genuinely unprecedented (no vendor SDK
    or COBOL mainframe format in the historical corpus), so retrieval finds nothing
    and the gate must trigger on the no-precedent signal."""
    assert TRANSCRIPT_PATH.exists(), "copy the S14 sample transcript before running this test"
    transcript = TRANSCRIPT_PATH.read_text(encoding="utf-8")

    async def backend(query, sectors):
        return []  # no historical precedent for either component

    monkeypatch.setattr("app.dependencies.get_llm_wrapper", lambda: _FakeWrapper())
    monkeypatch.setattr(
        "app.domain.graph.supervisor.agents.make_retrieval_backend", lambda **kwargs: backend
    )

    graph = build_supervisor_graph(MemorySaver())
    await graph.ainvoke({"transcript": transcript}, CONFIG)
    snap = await graph.aget_state(CONFIG)

    assert snap.next == ("human_review_gate",)
    assert snap.interrupts[0].value["gate"] == "low_confidence_estimate"
    assert snap.values["confidence"] == 0.0
