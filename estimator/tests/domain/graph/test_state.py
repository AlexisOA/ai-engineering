"""The accumulator fields (Annotated[..., operator.add]) merge across nodes."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.domain.graph.state import EstimationState


async def _node_a(state: EstimationState) -> dict:
    return {"budget_matches": [{"component": "A", "reference_budget_id": "b1", "amount": 10.0}]}


async def _node_b(state: EstimationState) -> dict:
    return {
        "budget_matches": [{"component": "B", "reference_budget_id": "b2", "amount": 20.0}],
        "errors": ["oops"],
    }


async def test_accumulator_fields_merge_across_nodes():
    builder = StateGraph(EstimationState)
    builder.add_node("a", _node_a)
    builder.add_node("b", _node_b)
    builder.add_edge(START, "a")
    builder.add_edge("a", "b")
    builder.add_edge("b", END)
    graph = builder.compile()

    result = await graph.ainvoke({"transcript": "x"})

    assert [m["component"] for m in result["budget_matches"]] == ["A", "B"]
    assert result["errors"] == ["oops"]


async def test_accumulator_starts_empty_when_no_node_contributes():
    builder = StateGraph(EstimationState)

    async def _noop(state: EstimationState) -> dict:
        return {}

    builder.add_node("noop", _noop)
    builder.add_edge(START, "noop")
    builder.add_edge("noop", END)
    graph = builder.compile()

    result = await graph.ainvoke({"transcript": "x"})
    assert result.get("budget_matches", []) == []
    assert result.get("errors", []) == []
