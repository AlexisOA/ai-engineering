"""Semantic search over persisted chunks (Session 8, no index yet — sequential scan)."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.schemas import SearchResponse, SearchResultItem
from app.generation.rag.store.models import ChunkRow


async def search(
    session: AsyncSession,
    *,
    embedder: OpenAIEmbedder,
    query: str,
    k: int,
) -> SearchResponse:
    t0 = time.perf_counter()
    query_vector = embedder.embed_one(query)

    distance = ChunkRow.embedding.cosine_distance(query_vector)
    stmt = (
        select(
            ChunkRow.id,
            ChunkRow.document_id,
            ChunkRow.chunk_type,
            ChunkRow.content,
            ChunkRow.chunk_metadata,
            distance.label("distance"),
        )
        .order_by(distance)
        .limit(k)
    )
    rows = (await session.execute(stmt)).all()

    results = [
        SearchResultItem(
            chunk_id=row.id,
            document_id=row.document_id,
            chunk_type=row.chunk_type,
            content=row.content,
            distance=round(row.distance, 4),
            metadata=row.chunk_metadata,
        )
        for row in rows
    ]
    return SearchResponse(
        query=query,
        k=k,
        search_time_ms=int((time.perf_counter() - t0) * 1000),
        results=results,
    )
