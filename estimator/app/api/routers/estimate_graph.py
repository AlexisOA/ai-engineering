"""``POST /v1/estimate/graph`` — the Session 13 LangGraph-driven estimation flow.

Same external contract as ``/v1/estimate/from-transcript``: a transcript in, a
structured estimate (plus ``status``) out. What runs underneath is now an
explicit, checkpointed graph instead of a fixed function pipeline — the
business backend never has to know.
"""

from __future__ import annotations

from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.rate_limiting import limiter
from app.api.security import require_estimate_key
from app.domain.graph.schemas import GraphEstimateRequest, GraphEstimateResponse

log = structlog.get_logger()

router = APIRouter(prefix="/v1/estimate", tags=["estimate"])


@router.post(
    "/graph",
    response_model=GraphEstimateResponse,
    dependencies=[Depends(require_estimate_key)],
)
@limiter.limit("10/minute")
async def estimate_graph(request: Request, payload: GraphEstimateRequest) -> GraphEstimateResponse:
    """Run the estimation graph end to end and return the estimate + status."""
    graph = request.app.state.graph
    if graph is None:
        raise HTTPException(status_code=503, detail="The estimation graph is not available.")

    thread_id = payload.estimation_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    try:
        result = await graph.ainvoke({"transcript": payload.transcript}, config)
    except Exception as exc:  # noqa: BLE001
        log.error("estimate_graph_failed", error_type=type(exc).__name__, error=str(exc)[:300])
        raise HTTPException(status_code=502, detail="Failed to produce a graph estimate.") from exc

    return GraphEstimateResponse(
        estimate=result.get("estimate"),
        status=result.get("status"),
        errors=result.get("errors", []),
    )
