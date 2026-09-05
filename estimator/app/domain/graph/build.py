"""Wire the five nodes into a compiled LangGraph StateGraph (Session 13)."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.domain.graph.nodes import (
    classify_components,
    extract_requirements,
    generate_estimate,
    make_search_budgets_node,
    validate_and_consolidate,
)
from app.domain.graph.state import EstimationState
from app.generation.rag.agent_retrieval import RetrievalBackend, default_retrieval_backend


def _route_on_status(state: EstimationState) -> str:
    """Level 3: an explicit conditional edge instead of a fixed one to END.

    Both branches currently land on END — the point is the mechanism, not a
    different destination; the live session adds a real retry/recovery target
    for "needs_review".
    """
    return state.get("status") or "needs_review"


def build_graph(checkpointer=None, *, retrieval_backend: RetrievalBackend | None = None):
    """Compile the estimation graph.

    ``retrieval_backend`` defaults to the real S9-S10 hybrid pipeline
    (``default_retrieval_backend``); pass the offline stub to run without a
    database (see ``scripts/run_graph_s13.py --stub``).
    """
    backend = retrieval_backend or default_retrieval_backend
    search_budgets = make_search_budgets_node(backend)

    builder = StateGraph(EstimationState)
    builder.add_node("extract_requirements", extract_requirements)
    builder.add_node("classify_components", classify_components)
    builder.add_node("search_budgets", search_budgets)  # sequential for now
    builder.add_node("generate_estimate", generate_estimate)
    builder.add_node("validate_and_consolidate", validate_and_consolidate)

    builder.add_edge(START, "extract_requirements")
    builder.add_edge("extract_requirements", "classify_components")
    builder.add_edge("classify_components", "search_budgets")
    builder.add_edge("search_budgets", "generate_estimate")
    builder.add_edge("generate_estimate", "validate_and_consolidate")
    builder.add_conditional_edges(
        "validate_and_consolidate", _route_on_status, {"validated": END, "needs_review": END}
    )

    return builder.compile(checkpointer=checkpointer)
