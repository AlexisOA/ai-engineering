"""Batched OpenAI embedder.

``embed_many`` sends chunks to ``client.embeddings.create`` in batches rather
than one call per chunk — the endpoint natively accepts a list of inputs, so
batching is strictly cheaper in round trips and latency.
"""

from __future__ import annotations

import time

import structlog
from openai import OpenAI, RateLimitError

from app.embedding_pipeline.schemas import Chunk, EmbeddedChunk

log = structlog.get_logger()

BATCH_SIZE = 100

# $ per 1M input tokens for text-embedding-3-small. This is a pricing fact,
# not a config value — it changes when OpenAI revises pricing, not per
# environment, so it stays a plain module constant rather than a Setting.
PRICE_PER_MILLION_TOKENS_USD = 0.02

_RETRY_DELAYS_SECONDS = (1, 2, 4)


def estimate_cost_usd(total_tokens: int) -> float:
    return (total_tokens / 1_000_000) * PRICE_PER_MILLION_TOKENS_USD


class OpenAIEmbedder:
    """Wraps one OpenAI embedding model with batching and rate-limit retry."""

    def __init__(self, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def embed_one(self, text: str) -> list[float]:
        """Embed a single string. Used by ``scripts/compare.py``."""
        return self._embed_batch([text])[0]

    def embed_many(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        embedded: list[EmbeddedChunk] = []
        for offset in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[offset : offset + BATCH_SIZE]
            embedded.extend(self._embed_chunk_batch(batch))
        return embedded

    def _embed_chunk_batch(self, batch: list[Chunk]) -> list[EmbeddedChunk]:
        t0 = time.perf_counter()
        vectors = self._embed_batch([chunk.text for chunk in batch])
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        batch_tokens = sum(chunk.token_count for chunk in batch)
        log.info(
            "embedding_batch_completed",
            model=self._model,
            chunks=len(batch),
            tokens=batch_tokens,
            latency_ms=latency_ms,
        )
        return [
            EmbeddedChunk(**chunk.model_dump(), embedding=vector)
            for chunk, vector in zip(batch, vectors, strict=True)
        ]

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """One API call for ``texts``, retrying on rate limits with a simple
        exponential backoff. Any other error propagates to the caller."""
        for attempt, delay in enumerate((*_RETRY_DELAYS_SECONDS, None)):
            try:
                response = self._client.embeddings.create(model=self._model, input=texts)
                return [item.embedding for item in response.data]
            except RateLimitError:
                if delay is None:
                    raise
                log.warning(
                    "embedding_rate_limited",
                    attempt=attempt + 1,
                    retry_in_seconds=delay,
                    batch_size=len(texts),
                )
                time.sleep(delay)
        raise AssertionError("unreachable: loop always returns or raises")
