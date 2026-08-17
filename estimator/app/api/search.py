"""``POST /search`` — semantic search over persisted chunks."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_embedder
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.retriever import search as run_search
from app.generation.rag.schemas import SearchRequest, SearchResponse
from app.generation.rag.store.db import get_db_session

log = structlog.get_logger()

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    embedder: OpenAIEmbedder | None = Depends(get_embedder),
    session: AsyncSession = Depends(get_db_session),
) -> SearchResponse:
    if embedder is None:
        log.error("search_failed", reason="embedder_unavailable")
        raise HTTPException(status_code=500, detail="Embedding service is not available.")

    response = await run_search(session, embedder=embedder, query=request.query, k=request.k)
    log.info("search_done", query=request.query, k=request.k, results=len(response.results))
    return response
