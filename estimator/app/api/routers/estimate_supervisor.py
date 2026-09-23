"""``/v1/estimate/supervisor`` — the supervisor multi-agent estimation flow (Session 14).

Same contract posture as ``estimate_graph.py``: the flow pauses at ONE human gate
(``low_confidence_estimate``), so the contract is three verbs over one
``thread_id``:

* ``POST /v1/estimate/supervisor`` — START. Runs until the gate or ``END`` and
  returns a ``SupervisorRunState`` (``state="paused"`` with ``pending_gate``, or
  ``state="completed"``).
* ``POST /v1/estimate/supervisor/{estimation_id}/resume`` — RESUME. Feeds the
  human's decision via ``Command(resume=...)``. Idempotent-guarded: resuming a run
  with nothing pending -> 409.
* ``GET /v1/estimate/supervisor/{estimation_id}/state`` — read the current
  snapshot.

The ``thread_id`` is prefixed (``supervisor:{estimation_id}``) so it never
collides with the Session 13 graph's own checkpoints even if a caller reuses the
same ``estimation_id`` against both endpoints — they share the same Postgres
checkpointer/pool, no new infrastructure.
"""

from __future__ import annotations

from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.types import Command

from app.api.deps import get_request_id
from app.api.rate_limiting import limiter
from app.api.security import require_estimate_key
from app.domain.schemas.supervisor_estimation import (
    SupervisorEstimateRequest,
    SupervisorPendingGate,
    SupervisorResumeRequest,
    SupervisorRunState,
)
from app.generation.rag.observability import log_stage

log = structlog.get_logger()

router = APIRouter(prefix="/v1/estimate", tags=["estimate-supervisor"])


def _thread_id(estimation_id: str) -> str:
    return f"supervisor:{estimation_id}"


def _require_supervisor_graph(request: Request, request_id: str):
    graph = getattr(request.app.state, "supervisor_graph", None)
    if graph is None:
        log.error("supervisor_graph_unavailable", request_id=request_id)
        raise HTTPException(status_code=503, detail="Supervisor graph is not available.")
    return graph


def _build_run_state(estimation_id: str, snapshot) -> SupervisorRunState:
    values = snapshot.values or {}
    paused = bool(snapshot.next)
    pending_gate = None
    interrupts = getattr(snapshot, "interrupts", None) or ()
    if paused and interrupts:
        gate_value = interrupts[0].value or {}
        pending_gate = SupervisorPendingGate(
            gate=gate_value.get("gate", "unknown"),
            estimation_id=estimation_id,
            payload={k: v for k, v in gate_value.items() if k not in ("gate", "estimation_id")},
        )
    return SupervisorRunState(
        estimation_id=estimation_id,
        state="paused" if paused else "completed",
        pending_gate=pending_gate,
        requirements=values.get("requirements") or [],
        components=values.get("components") or [],
        budget_matches=values.get("budget_matches") or [],
        estimate=values.get("estimate"),
        validation=values.get("validation"),
        confidence=values.get("confidence"),
        status=values.get("status"),
        agent_contributions=values.get("agent_contributions") or [],
        errors=values.get("errors") or [],
    )


@router.post(
    "/supervisor",
    response_model=SupervisorRunState,
    dependencies=[Depends(require_estimate_key)],
)
@limiter.limit("10/minute")
async def estimate_supervisor(
    request: Request, payload: SupervisorEstimateRequest
) -> SupervisorRunState:
    """START the supervisor flow; runs to the human gate or to completion."""
    request_id = get_request_id(request)
    graph = _require_supervisor_graph(request, request_id)

    estimation_id = payload.estimation_id or str(uuid4())
    config = {"configurable": {"thread_id": _thread_id(estimation_id)}}
    try:
        with log_stage("supervisor_estimate_start", request_id, estimation_id=estimation_id):
            await graph.ainvoke({"transcript": payload.transcript}, config)
            snapshot = await graph.aget_state(config)
    except Exception as exc:  # noqa: BLE001 — any node/LLM failure -> 502.
        log.error(
            "supervisor_estimate_failed",
            request_id=request_id,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        raise HTTPException(status_code=502, detail="Failed to produce an estimate.") from exc

    return _build_run_state(estimation_id, snapshot)


@router.post(
    "/supervisor/{estimation_id}/resume",
    response_model=SupervisorRunState,
    dependencies=[Depends(require_estimate_key)],
)
@limiter.limit("10/minute")
async def resume_supervisor(
    request: Request, estimation_id: str, payload: SupervisorResumeRequest
) -> SupervisorRunState:
    """RESUME a paused run with the human's decision."""
    request_id = get_request_id(request)
    graph = _require_supervisor_graph(request, request_id)
    config = {"configurable": {"thread_id": _thread_id(estimation_id)}}

    snapshot = await graph.aget_state(config)
    if not snapshot.next:
        raise HTTPException(
            status_code=409,
            detail="No pending human gate for this estimation_id (already completed or unknown).",
        )

    try:
        with log_stage("supervisor_estimate_resume", request_id, estimation_id=estimation_id):
            await graph.ainvoke(Command(resume=payload.decision), config)
            snapshot = await graph.aget_state(config)
    except Exception as exc:  # noqa: BLE001 — any node/LLM failure -> 502.
        log.error(
            "supervisor_estimate_resume_failed",
            request_id=request_id,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        raise HTTPException(status_code=502, detail="Failed to resume the estimate.") from exc

    return _build_run_state(estimation_id, snapshot)


@router.get(
    "/supervisor/{estimation_id}/state",
    response_model=SupervisorRunState,
    dependencies=[Depends(require_estimate_key)],
)
@limiter.limit("60/minute")
async def supervisor_state(request: Request, estimation_id: str) -> SupervisorRunState:
    """Read the current snapshot of a run (pending gate + artifacts)."""
    request_id = get_request_id(request)
    graph = _require_supervisor_graph(request, request_id)
    config = {"configurable": {"thread_id": _thread_id(estimation_id)}}
    snapshot = await graph.aget_state(config)
    if not snapshot.created_at and not snapshot.values:
        raise HTTPException(status_code=404, detail="Unknown estimation_id.")
    return _build_run_state(estimation_id, snapshot)
