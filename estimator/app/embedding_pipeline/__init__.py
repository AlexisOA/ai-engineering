"""Minimal chunking + embedding pipeline for historical budget JSON (Session 7).

Turns normalized budget records into embedded chunks, in memory, over HTTP.
Persistence (pgvector) and retrieval are out of scope until Session 8; this
module only produces vectors and a CLI sanity check that they discriminate
between related and unrelated texts.

- ``schemas``  — ``Budget`` / ``BudgetComponent`` input, ``Chunk`` /
  ``EmbeddedChunk`` output.
- ``chunker``  — ``JSONStructuralChunker``: one budget component = one chunk.
- ``embedder`` — ``OpenAIEmbedder``: batched calls to ``text-embedding-3-small``.
- ``router``   — ``POST /embeddings/ingest``.
"""
