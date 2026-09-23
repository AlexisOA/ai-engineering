"""The hand-built supervisor node — routes by state, not by an LLM call.

Deterministic on purpose: the sequence a transcript needs (extract, then search,
then estimate, then validate, then review) is fixed by what data each step needs
from the previous one, so there is nothing a per-step model call would decide
that inspecting the state does not already tell us — see ARCHITECTURE discussion
in the session's write-up. Every decision is still logged with its reason, so the
routing is as visible in the trace as an LLM-driven router's would be, without
paying a model call per hop.

Built with ``StateGraph`` + ``Command`` by hand (no ``create_supervisor``), as the
exercise asks, so every ``goto`` shows up explicitly in ``build.py``'s edges and in
this function's own log line.
"""

from __future__ import annotations

from typing import Literal

import structlog
from langgraph.types import Command

from app.domain.graph.supervisor.state import SupervisorState

log = structlog.get_logger()

Destination = Literal[
    "requirements_extractor",
    "budget_searcher",
    "estimate_generator",
    "coherence_validator",
    "human_review_gate",
]


def _has_run(state: SupervisorState, agent: str) -> bool:
    """Whether ``agent`` already contributed at least once.

    Routing on the DATA a step produces (``not state.get("budget_matches")``) is
    wrong: an edge-case transcript with no historical precedent legitimately
    leaves ``budget_matches`` empty forever, and the supervisor would loop back to
    ``budget_searcher`` indefinitely. Routing on whether the step RAN (recorded in
    ``agent_contributions`` regardless of what it found) is the correct signal —
    "no results" and "never ran" are different states.
    """
    return any(c.get("agent") == agent for c in state.get("agent_contributions") or [])


def supervisor(state: SupervisorState) -> Command[Destination]:
    """Decide the next specialist to run based on which ones have already run."""
    if not _has_run(state, "requirements_extractor"):
        goto, reason = "requirements_extractor", "requirements_extractor has not run yet"
    elif not _has_run(state, "budget_searcher"):
        goto, reason = "budget_searcher", "budget_searcher has not run yet"
    elif not _has_run(state, "estimate_generator"):
        goto, reason = "estimate_generator", "estimate_generator has not run yet"
    elif not _has_run(state, "coherence_validator"):
        goto, reason = "coherence_validator", "coherence_validator has not run yet"
    else:
        goto, reason = "human_review_gate", "all specialists ran, ready for human review"

    log.info("supervisor_route", goto=goto, reason=reason)
    return Command(goto=goto)
