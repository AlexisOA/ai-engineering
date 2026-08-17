"""Session 10 golden-set evaluation: precision@5 and latency for A/B/C/D.

    A = vector,  rerank off       B = hybrid, rerank off
    C = vector,  rerank on        D = hybrid, rerank on

Usage::

    uv run python scripts/eval_retrieval_s10.py
    # or inside the container:
    docker compose exec estimator python scripts/eval_retrieval_s10.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.dependencies import get_retrieval_pipeline  # noqa: E402

GOLDEN_SET_PATH = ROOT / "evals" / "golden_retrieval.json"
FINAL_K = 5
RECALL_K = 50

CONFIGS = [
    ("A", "vector", False),
    ("B", "hybrid", False),
    ("C", "vector", True),
    ("D", "hybrid", True),
]


def precision_at_k(chunks, relevant_budget_ids: set[str]) -> float:
    if not chunks:
        return 0.0
    hits = sum(1 for c in chunks if c.metadata.get("budget_id") in relevant_budget_ids)
    return hits / len(chunks)


async def run_config(pipeline, mode: str, rerank: bool, golden_set: list[dict]) -> dict:
    precisions = []
    latencies = []
    for case in golden_set:
        result = await pipeline.retrieve(
            case["query"],
            mode=mode,
            rerank=rerank,
            recall_k=RECALL_K,
            final_k=FINAL_K,
        )
        precisions.append(precision_at_k(result.chunks, set(case["relevant_budget_ids"])))
        latencies.append(result.latency_ms)
    return {
        "mean_precision": sum(precisions) / len(precisions),
        "mean_latency_ms": sum(latencies) / len(latencies),
        "per_query_precision": precisions,
    }


async def main() -> int:
    golden_set = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    pipeline = get_retrieval_pipeline()
    if pipeline is None:
        print("ERROR: no OPENAI_API_KEY configured.", file=sys.stderr)
        return 1

    rows = []
    for label, mode, rerank in CONFIGS:
        print(f"running config {label} (mode={mode}, rerank={rerank})...")
        stats = await run_config(pipeline, mode, rerank, golden_set)
        rows.append((label, mode, rerank, stats))
        print(
            f"  precision@{FINAL_K}={stats['mean_precision']:.2f}  "
            f"latency_ms={stats['mean_latency_ms']:.0f}  "
            f"per_query={[round(p, 2) for p in stats['per_query_precision']]}"
        )

    print()
    print(f"| Config | Search | Reranking | Precision@{FINAL_K} | Latency (ms) |")
    print("|---|---|---|---|---|")
    for label, mode, rerank, stats in rows:
        search_label = "Vectorial" if mode == "vector" else "Híbrida"
        rerank_label = "Sí" if rerank else "No"
        print(
            f"| {label} | {search_label} | {rerank_label} | "
            f"{stats['mean_precision']:.2f} | {stats['mean_latency_ms']:.0f} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
