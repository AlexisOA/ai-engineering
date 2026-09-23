"""The supervisor flow's state — the Session 13 ``EstimationState``, extended.

``SupervisorState`` subclasses ``EstimationState`` rather than redeclaring it, so it
inherits ``transcript``, ``requirements``, ``budget_matches`` (``operator.add``
reducer) and ``errors`` (``operator.add`` reducer) with their reducers intact.
``app/domain/graph/state.py`` is not touched.

Two new fields carry what this session adds:

* ``validation`` / ``confidence`` — the coherence_validator's verdict and the
  estimate_generator's confidence score (the distance-weighted consensus
  reliability), read by the human gate to decide whether to pause.
* ``agent_contributions`` — the audit trail (Level 3): one row per tool call an
  agent made, successful or denied. Plain ``operator.add`` concat is enough here
  (unlike the Session 13 live ``task_hours`` fan-out) because nothing in this flow
  re-enters the same node twice with new contributions except the human gate, and
  the gate is written to only ever append its row AFTER ``interrupt()`` returns —
  so a resume's re-execution never re-appends.
"""

from __future__ import annotations

import operator
from typing import Annotated, Optional

from typing_extensions import TypedDict

from app.domain.graph.state import EstimationState


class AgentContribution(TypedDict, total=False):
    """One auditable action: which agent, which tool (if any), what happened."""

    agent: str
    tool: Optional[str]  # None = a plain LLM call, no tool involved
    outcome: str  # "ok" | "denied" | "error"
    detail: str  # short human-readable summary


class SupervisorState(EstimationState, total=False):
    """The Session 13 state, extended with the supervisor flow's own fields."""

    validation: Optional[dict]  # {"ok": bool, "issues": [...]}
    confidence: Optional[float]  # 0..1, from estimate_generator's consensus
    agent_contributions: Annotated[list[AgentContribution], operator.add]
    human_decision: Optional[dict]  # the resume payload, kept for audit
