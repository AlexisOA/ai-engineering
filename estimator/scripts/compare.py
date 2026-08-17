#!/usr/bin/env python3
"""Embed two texts and print their cosine similarity.

A minimal sanity check that the embedding pipeline works end-to-end and that
its vectors discriminate between related and unrelated texts — not a formal
retrieval-quality evaluation.

Usage::

    uv run python scripts/compare.py \\
        --text-a "OAuth 2.0 authentication backend for fintech" \\
        --text-b "JWT-based authorization service for banking app"

    # or, inside docker:
    docker compose exec estimator python scripts/compare.py --text-a "..." --text-b "..."

Cosine similarity is computed by hand (dot product / product of norms) with
only the standard library — no numpy/scikit-learn for a two-vector
comparison.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openai import OpenAI  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.embedding_pipeline.embedder import OpenAIEmbedder  # noqa: E402


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        raise ValueError("cannot compute cosine similarity against a zero vector")
    return dot / (norm_a * norm_b)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text-a", required=True)
    parser.add_argument("--text-b", required=True)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        parser.error("OPENAI_API_KEY must be set (in .env or the environment)")

    embedder = OpenAIEmbedder(
        client=OpenAI(api_key=settings.OPENAI_API_KEY),
        model=settings.EMBEDDING_MODEL,
    )
    vector_a = embedder.embed_one(args.text_a)
    vector_b = embedder.embed_one(args.text_b)
    similarity = cosine_similarity(vector_a, vector_b)

    print(f"Text A: {args.text_a}")
    print(f"Text B: {args.text_b}")
    print(f"Cosine similarity: {similarity:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
