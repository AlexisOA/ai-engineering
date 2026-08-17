"""``POST /embeddings/ingest``: chunk + embed a batch of budgets, in memory.

Thin router: chunking and embedding logic live in ``chunker.py`` /
``embedder.py``. This module only orchestrates the two calls, assembles the
response stats, and maps unexpected embedder failures to a 500.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_embedder
from app.embedding_pipeline.chunker import JSONStructuralChunker
from app.embedding_pipeline.embedder import OpenAIEmbedder, estimate_cost_usd
from app.embedding_pipeline.schemas import IngestRequest, IngestResponse, IngestStats

log = structlog.get_logger()

router = APIRouter(prefix="/embeddings", tags=["embeddings"])

_chunker = JSONStructuralChunker()


@router.post("/ingest", response_model=IngestResponse)
def ingest(
    request: IngestRequest,
    embedder: OpenAIEmbedder = Depends(get_embedder),
) -> IngestResponse:
    chunks = _chunker.chunk(request.budgets)

    try:
        embedded = embedder.embed_many(chunks)
    except Exception as exc:  # noqa: BLE001
        log.error(
            "embedding_ingest_failed",
            error_type=type(exc).__name__,
            error=str(exc)[:400],
            budgets=len(request.budgets),
            chunks=len(chunks),
        )
        raise HTTPException(
            status_code=500, detail="Failed to generate embeddings"
        ) from exc

    total_tokens = sum(chunk.token_count for chunk in chunks)
    log.info(
        "embedding_ingest_completed",
        budgets=len(request.budgets),
        chunks=len(chunks),
        total_tokens=total_tokens,
    )
    return IngestResponse(
        chunks=embedded,
        stats=IngestStats(
            total_budgets=len(request.budgets),
            total_chunks=len(chunks),
            total_tokens=total_tokens,
            estimated_cost_usd=estimate_cost_usd(total_tokens),
        ),
    )
