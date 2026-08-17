#!/usr/bin/env python3
"""Runs five representative queries against POST /search and prints the top-5.

Usage::

    docker compose run --rm estimator python scripts/query_examples.py
    # or, outside the container:
    uv run python scripts/query_examples.py
"""

from __future__ import annotations

import os

import httpx

BASE_URL = os.environ.get("SEARCH_BASE_URL", "http://localhost:8000")

QUERIES = [
    "REST API development with JWT authentication for financial sector",
    "secure backend service with token-based access control for banking applications",
    "mobile application for restaurant reservations",
    "integration with external system",
    "migration from monolith to microservices architecture using Kubernetes",
]


def main() -> int:
    lines: list[str] = []
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        for query in QUERIES:
            response = client.post("/search", json={"query": query, "k": 5})
            response.raise_for_status()
            data = response.json()

            lines.append(f"Query: {query}")
            lines.append(f"search_time_ms: {data['search_time_ms']}")
            for r in data["results"]:
                preview = r["content"][:120].replace("\n", " ")
                lines.append(
                    f"  chunk_id={r['chunk_id']:<5} distance={r['distance']:.4f} "
                    f"type={r['chunk_type']:<18} {preview}"
                )
            lines.append("")

    output = "\n".join(lines)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
