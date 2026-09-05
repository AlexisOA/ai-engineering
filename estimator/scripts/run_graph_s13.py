#!/usr/bin/env python3
"""Run the Session 13 estimation graph over a transcript, outside HTTP.

Usage::

    # Cheap debugging, offline stub (no DB, no OpenAI):
    uv run python scripts/run_graph_s13.py \\
        exercises/session-12/sample_transcript_simple.txt --stub --model claude-haiku-4-5

    # Real run (deliverable), complex transcript:
    uv run python scripts/run_graph_s13.py \\
        exercises/session-12/sample_transcript_complex.txt --stub --model claude-sonnet-4-5 \\
        --out exercises/session-13/trace_complex.txt

``--stub`` swaps the real S9-S10 retrieval pipeline (``make_retrieval_backend``,
needs OPENAI_API_KEY for embeddings) for
``exercises/session-12/reference_retrieval.py``'s canned corpus — the exercise's
own scaffolding safety net, reused as-is. ``--model`` overrides
``settings.AGENT_MODEL`` for this process only (``.env`` untouched); pass a
Claude model when OpenAI credit is unavailable — the graph's LLM nodes go
through the same ``LLMWrapper`` the rest of the service uses, so this needs no
separate code path (unlike Session 12's Responses-API-only agent loop).

Logfire spans (one per node, per ``app/domain/graph/observability.py``) print
to the console; redirect or ``--out`` to keep them with the run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# psycopg's async mode cannot run on Windows' default ProactorEventLoop
# (needed for the AsyncPostgresSaver checkpointer).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.domain.graph.build import build_graph  # noqa: E402
from app.domain.graph.checkpointer import open_checkpointer  # noqa: E402
from app.domain.graph.observability import configure_logfire  # noqa: E402


def _stub_backend():
    exercises_dir = ROOT / "exercises" / "session-12"
    if str(exercises_dir) not in sys.path:
        sys.path.insert(0, str(exercises_dir))
    from reference_retrieval import search_budgets_stub

    async def backend(query: str, sectors: list[str] | None) -> list[dict]:
        return search_budgets_stub(query, {"sectors": sectors} if sectors else None)

    return backend


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument(
        "--model", default=None, help="Overrides settings.AGENT_MODEL for this run."
    )
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Use the offline reference_retrieval.py stub instead of the real pipeline.",
    )
    parser.add_argument(
        "--thread-id", default=None, help="Checkpointer thread_id; a uuid4 is minted if omitted."
    )
    parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Skip Postgres entirely (quick offline debugging of the loop mechanics only — "
        "the real deliverable run needs the checkpointer, per the exercise's Level 2).",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    configure_logfire()

    settings = get_settings()
    if args.model:
        settings.AGENT_MODEL = args.model

    backend = _stub_backend() if args.stub else None
    transcript = args.transcript.read_text(encoding="utf-8")

    from uuid import uuid4

    thread_id = args.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    if args.no_checkpoint:
        graph = build_graph(retrieval_backend=backend)
        result = await graph.ainvoke({"transcript": transcript}, config)
    else:
        async with open_checkpointer(settings) as checkpointer:
            graph = build_graph(checkpointer, retrieval_backend=backend)
            result = await graph.ainvoke({"transcript": transcript}, config)

    report = (
        f"thread_id: {thread_id}\n"
        f"status: {result.get('status')}\n"
        f"requirements: {json.dumps(result.get('requirements', []), indent=2)}\n"
        f"components: {json.dumps(result.get('components', []), indent=2)}\n"
        f"budget_matches: {json.dumps(result.get('budget_matches', []), indent=2)}\n"
        f"errors: {json.dumps(result.get('errors', []), indent=2)}\n"
        f"estimate: {json.dumps(result.get('estimate'), indent=2)}\n"
    )
    print(report)

    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
