"""Sanity check: does the reranker model download and score correctly?

Run with::

    docker compose exec estimator python -m app.generation.rag.retrieval.verify_reranker
"""

from __future__ import annotations

import sys

from app.generation.rag.retrieval.reranker import CrossEncoderReranker


def main() -> int:
    reranker = CrossEncoderReranker.from_settings()
    print(f"loading model: {reranker.model_name}")
    reranker.load()

    query = "mobile banking authentication with OAuth"
    documents = [
        "OAuth 2.0 authentication backend for a fintech mobile app",
        "Warehouse inventory tracking with barcode scanners",
    ]
    scores = reranker.score(query, documents)
    print(f"scores: {scores}")

    if scores[0] <= scores[1]:
        print("ERROR: the on-topic document did not score higher.", file=sys.stderr)
        return 1

    print("OK: reranker loaded and scored as expected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
