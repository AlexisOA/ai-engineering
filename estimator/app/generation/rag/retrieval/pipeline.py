"""Recall-then-rerank retrieval pipeline (Session 10).

Two independent knobs map onto the exercise's four configurations:

- ``mode``   — ``"vector"`` (existing Session 8/9 k-NN) or ``"hybrid"``
  (vector + lexical full-text, fused with RRF).
- ``rerank`` — whether a cross-encoder rescores the recalled set before the
  final cut (recall wide at ``recall_k``, keep only ``final_k``).

    A = vector,  rerank=False       B = hybrid, rerank=False
    C = vector,  rerank=True        D = hybrid, rerank=True
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Literal

import structlog
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.retrieval.fusion import reciprocal_rank_fusion
from app.generation.rag.retrieval.reranker import CrossEncoderReranker
from app.generation.rag.store.repository import ChunkStore

log = structlog.get_logger()

RetrievalMode = Literal["vector", "hybrid"]


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    chunk_type: str
    content: str
    metadata: dict


@dataclass
class PipelineResult:
    chunks: list[RetrievedChunk]
    latency_ms: int


def _from_vector_row(row: Row) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row.id,
        document_id=row.document_id,
        chunk_type=row.chunk_type,
        content=row.content,
        metadata=row.metadata_,
    )


def _from_lexical_row(row: Row) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row.id,
        document_id=row.document_id,
        chunk_type=row.chunk_type,
        content=row.content,
        metadata=row.metadata,
    )


class RetrievalPipeline:
    """Wires the embedder + vector/lexical store search + RRF + reranker."""

    def __init__(
        self,
        embedder: OpenAIEmbedder,
        session_factory: async_sessionmaker,
        store: ChunkStore,
        reranker: CrossEncoderReranker | None = None,
    ) -> None:
        self._embedder = embedder
        self._session_factory = session_factory
        self._store = store
        self._reranker = reranker

    async def retrieve(
        self,
        query: str,
        *,
        mode: RetrievalMode = "vector",
        rerank: bool = False,
        recall_k: int = 50,
        final_k: int = 5,
    ) -> PipelineResult:
        started = time.perf_counter()
        query_vector = await asyncio.to_thread(self._embedder.embed_one, query)

        async with self._session_factory() as session:
            vector_rows = await self._store.search(session, query_vector=query_vector, k=recall_k)
            by_id = {row.id: _from_vector_row(row) for row in vector_rows}

            if mode == "hybrid":
                lexical_rows = await self._store.search_lexical(session, query=query, k=recall_k)
                for row in lexical_rows:
                    by_id.setdefault(row.id, _from_lexical_row(row))

                fused = reciprocal_rank_fusion(
                    [
                        [row.id for row in vector_rows],
                        [row.id for row in lexical_rows],
                    ]
                )
                ordered = [by_id[chunk_id] for chunk_id, _score in fused if chunk_id in by_id]
            else:
                ordered = [by_id[row.id] for row in vector_rows]

        if rerank and self._reranker is not None:
            final = self._reranker.rerank(query, ordered, top_n=final_k, text_of=lambda c: c.content)
        else:
            final = ordered[:final_k]

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "retrieval_pipeline_done",
            mode=mode,
            rerank=rerank,
            recall_k=recall_k,
            final_k=final_k,
            results=len(final),
            latency_ms=elapsed_ms,
        )
        return PipelineResult(chunks=final, latency_ms=elapsed_ms)
