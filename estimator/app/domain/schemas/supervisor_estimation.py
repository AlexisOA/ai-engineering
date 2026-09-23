"""The public contract for the supervisor estimate endpoint (Session 14).

Same "transcript in, structured estimate + status out" posture as
``graph_estimation.py``, extended with the supervisor's own artifacts
(``validation``, ``confidence``, ``agent_contributions``) and a single human gate
(``graph_estimation.py`` has two).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.graph.state import BudgetMatch, Component
from app.domain.graph.supervisor.state import AgentContribution


class SupervisorEstimateRequest(BaseModel):
    """Payload for ``POST /v1/estimate/supervisor``."""

    transcript: str = Field(min_length=100, max_length=50_000)
    estimation_id: str | None = Field(default=None, max_length=128)


class SupervisorResumeRequest(BaseModel):
    """Payload for ``POST /v1/estimate/supervisor/{estimation_id}/resume``.

    ``decision`` is free-form: the human's answer to the ``low_confidence_estimate``
    gate, e.g. ``{"approved": true}`` or ``{"approved": false, "status":
    "needs_review", "notes": "..."}``. Any HTTP client can drive it.
    """

    decision: dict = Field(default_factory=dict)


class SupervisorPendingGate(BaseModel):
    """The human gate a paused run is waiting on (the ``interrupt`` payload)."""

    gate: str  # "low_confidence_estimate"
    estimation_id: str
    payload: dict = Field(default_factory=dict)


class SupervisorRunState(BaseModel):
    """A snapshot of the supervisor run: either paused at the gate, or completed."""

    estimation_id: str
    state: str  # "paused" | "completed"
    pending_gate: SupervisorPendingGate | None = None
    requirements: list[str] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    budget_matches: list[BudgetMatch] = Field(default_factory=list)
    estimate: dict | None = None
    validation: dict | None = None
    confidence: float | None = None
    status: str | None = None  # "validated" | "needs_review"
    agent_contributions: list[AgentContribution] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
