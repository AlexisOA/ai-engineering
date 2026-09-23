"""Wire and compile the supervisor graph (Session 14).

    START → supervisor
    supervisor ──Command(goto)──▶ {requirements_extractor, budget_searcher,
                                    estimate_generator, coherence_validator,
                                    human_review_gate}
    {the 4 specialists} ──edge──▶ supervisor          (return to the hub)
    human_review_gate ──Command(goto)──▶ END           (directly, or after interrupt/resume)

The supervisor is the single point every routing decision passes through — each
specialist reports back to it rather than to the next specialist directly, so the
trace shows one supervisor decision per hop (the topology the exercise's article
calls "cooperation": each agent contributes a distinct, non-overlapping piece).

A checkpointer is REQUIRED (not optional) for the human gate's ``interrupt()`` to
persist across the pause — same requirement as the Session 13 live graph.
"""

from __future__ import annotations

from langgraph.graph import START, StateGraph

from app.domain.graph.supervisor.agents import (
    budget_searcher,
    coherence_validator,
    estimate_generator,
    requirements_extractor,
)
from app.domain.graph.supervisor.gate import human_review_gate
from app.domain.graph.supervisor.state import SupervisorState
from app.domain.graph.supervisor.supervisor import supervisor

SPECIALISTS = (
    "requirements_extractor",
    "budget_searcher",
    "estimate_generator",
    "coherence_validator",
)


def build_supervisor_graph(checkpointer=None):
    """Build and compile the supervisor + specialists graph."""
    builder = StateGraph(SupervisorState)

    builder.add_node("supervisor", supervisor)
    builder.add_node("requirements_extractor", requirements_extractor)
    builder.add_node("budget_searcher", budget_searcher)
    builder.add_node("estimate_generator", estimate_generator)
    builder.add_node("coherence_validator", coherence_validator)
    builder.add_node("human_review_gate", human_review_gate)

    builder.add_edge(START, "supervisor")
    for name in SPECIALISTS:
        builder.add_edge(name, "supervisor")
    # human_review_gate routes to END via its own Command(goto=...) — no static edge
    # (same "handover, no edge" rule the Session 13 build.py documents).

    return builder.compile(checkpointer=checkpointer)
