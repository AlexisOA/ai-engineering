"""Chunk + embed + persist a single document, atomically."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.rag.chunking.structural import JSONStructuralChunker
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.schemas import Budget, IngestResponse
from app.generation.rag.store.models import ChunkRow, DocumentRow


class DuplicateDocumentError(Exception):
    def __init__(self, document_id: int) -> None:
        self.document_id = document_id


async def ingest_document(
    session: AsyncSession,
    *,
    chunker: JSONStructuralChunker,
    embedder: OpenAIEmbedder,
    source_path: str,
    document_type: str,
    content: Budget,
) -> IngestResponse:
    t0 = time.perf_counter()

    existing_id = await session.scalar(
        select(DocumentRow.id).where(DocumentRow.source_path == source_path)
    )
    if existing_id is not None:
        raise DuplicateDocumentError(existing_id)

    document = DocumentRow(source_path=source_path, document_type=document_type)
    session.add(document)
    await session.flush()

    chunks = chunker.chunk([content])
    embedded = embedder.embed_many(chunks)

    session.add_all(
        ChunkRow(
            document_id=document.id,
            chunk_type="budget_component",
            content=chunk.text,
            embedding=chunk.embedding,
            chunk_metadata=chunk.metadata,
        )
        for chunk in embedded
    )
    await session.commit()

    dimension = len(embedded[0].embedding) if embedded else 0
    return IngestResponse(
        document_id=document.id,
        chunks_created=len(embedded),
        embedding_dimension=dimension,
        ingestion_time_ms=int((time.perf_counter() - t0) * 1000),
    )
