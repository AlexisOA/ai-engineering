"""The human review gate (Level 2) — pauses the flow when the estimate is not trustworthy.

Triggers on any of the three signals the exercise names: low confidence, an
estimate the coherence_validator flagged as incoherent/out of range, or a
component with no historical precedent at all (an empty search). When triggered,
``interrupt()`` persists the state in the Session 13 Postgres checkpointer and
the run stops until a resume supplies the human's decision.

``interrupt()`` re-executes this node's body from the top on resume, so nothing
before the ``interrupt()`` call may have side effects that should not repeat. The
audit row for this node is only appended to ``agent_contributions`` AFTER
``interrupt()`` returns — the pre-interrupt half writes nothing to the
accumulator, so a resume never produces a duplicate row.
"""

from __future__ import annotations

from typing import Literal

import structlog
from langgraph.types import Command, interrupt

from app.config import get_settings
from app.domain.graph.supervisor.state import SupervisorState

log = structlog.get_logger()


def _trigger_reason(state: SupervisorState) -> str | None:
    """Return why the gate should pause, or ``None`` if the estimate is trustworthy."""
    settings = get_settings()
    confidence = state.get("confidence")
    if confidence is not None and confidence < settings.SUPERVISOR_CONFIDENCE_THRESHOLD:
        return f"confidence {confidence} below threshold {settings.SUPERVISOR_CONFIDENCE_THRESHOLD}"

    validation = state.get("validation") or {}
    if not validation.get("ok", True):
        return f"estimate failed coherence checks: {validation.get('issues')}"

    matches = state.get("budget_matches") or []
    matched_components = {m["component"] for m in matches}
    components = state.get("components") or []
    unmatched = [c["name"] for c in components if c["name"] not in matched_components]
    if unmatched:
        return f"no historical precedent for: {unmatched}"

    return None


def human_review_gate(state: SupervisorState) -> Command[Literal["__end__"]]:
    """Pause for human review when the estimate is not trustworthy, else finish."""
    reason = _trigger_reason(state)
    if reason is None:
        log.info("supervisor_gate_skipped")
        contribution = {
            "agent": "human_review_gate",
            "tool": None,
            "outcome": "ok",
            "detail": "estimate trustworthy, gate skipped",
        }
        return Command(goto="__end__", update={"agent_contributions": [contribution]})

    log.info("supervisor_gate_triggered", reason=reason)
    decision = interrupt(
        {
            "gate": "low_confidence_estimate",
            "reason": reason,
            "estimate": state.get("estimate"),
            "confidence": state.get("confidence"),
            "validation": state.get("validation"),
        }
    )
    contribution = {
        "agent": "human_review_gate",
        "tool": None,
        "outcome": "ok",
        "detail": f"human decision: {decision}"[:200],
    }
    status = state.get("status")
    if isinstance(decision, dict) and "status" in decision:
        status = decision["status"]
    log.info("supervisor_gate_resumed", decision=decision)
    return Command(
        goto="__end__",
        update={
            "human_decision": decision,
            "status": status,
            "agent_contributions": [contribution],
        },
    )
