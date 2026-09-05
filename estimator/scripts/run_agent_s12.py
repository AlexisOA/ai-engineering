#!/usr/bin/env python3
"""Run the Session 12 agent (real Responses API loop) over a transcript.

Usage::

    # Cheap loop-mechanics debugging (simple transcript, gpt-5-mini):
    uv run python scripts/run_agent_s12.py \\
        exercises/session-12/sample_transcript_simple.txt --model gpt-5-mini --effort minimal

    # Real run (deliverable), complex transcript, gpt-5 medium effort:
    uv run python scripts/run_agent_s12.py \\
        exercises/session-12/sample_transcript_complex.txt --model gpt-5 --effort medium \\
        --out exercises/session-12/trace_complex.txt

    # Offline debugging without a database (the exercise's own safety-net stub):
    uv run python scripts/run_agent_s12.py \\
        exercises/session-12/sample_transcript_simple.txt --stub

``--stub`` swaps the real S9-S10 retrieval pipeline for
``exercises/session-12/reference_retrieval.py``'s canned corpus — no Postgres,
no embeddings call, just the loop mechanics.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.dependencies import get_agent_retrieval_backend, get_async_openai_client  # noqa: E402
from app.generation.agentic.agent_loop import render_trace, run_agent  # noqa: E402


def _stub_backend():
    """Wrap the offline reference_retrieval.py stub as an async RetrievalBackend."""
    exercises_dir = ROOT / "exercises" / "session-12"
    if str(exercises_dir) not in sys.path:
        sys.path.insert(0, str(exercises_dir))
    from reference_retrieval import search_budgets_stub

    async def backend(query: str, filters: dict | None) -> list[dict]:
        return search_budgets_stub(query, filters)

    return backend


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Session 12 hand-rolled agent.")
    parser.add_argument("transcript", type=Path, help="Path to a transcript .txt file.")
    parser.add_argument("--model", default=None, help="Overrides settings.AGENT_MODEL.")
    parser.add_argument("--effort", default=None, choices=["minimal", "low", "medium", "high"])
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Use the offline reference_retrieval.py stub instead of the real pipeline.",
    )
    parser.add_argument("--out", type=Path, default=None, help="Also write the trace to this file.")
    args = parser.parse_args()

    settings = get_settings()
    model = args.model or settings.AGENT_MODEL
    effort = args.effort or settings.AGENT_REASONING_EFFORT
    max_iterations = args.max_iterations or settings.AGENT_MAX_ITERATIONS

    client = get_async_openai_client()
    if client is None:
        print("ERROR: OPENAI_API_KEY is not configured.", file=sys.stderr)
        return 1

    backend = _stub_backend() if args.stub else get_agent_retrieval_backend()
    transcript = args.transcript.read_text(encoding="utf-8")

    result = await run_agent(
        transcript,
        client=client,
        model=model,
        reasoning_effort=effort,
        max_iterations=max_iterations,
        retrieval_backend=backend,
    )

    trace_text = render_trace(result.trace)
    report = (
        f"{trace_text}\n"
        f"FINAL ESTIMATE  (iterations={result.iterations}, stopped={result.stopped_reason})\n"
        f"{result.estimate.model_dump_json(indent=2)}\n"
    )
    print(report)

    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
