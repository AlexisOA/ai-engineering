#!/usr/bin/env python3
"""RAGAS generation-quality baseline (Session 11).

Runs the golden set (``evals/golden_generation_s11.json``, the 5 budget-only
queries from Session 10 with a hand-written reference estimate each) through
the REAL pipeline — reformulate -> embed -> retrieve -> assemble -> generate ->
verify_citations, the exact same pure functions ``estimate_from_transcript``
composes (app/generation/rag/estimator.py) — and scores each answer with the
four RAGAS metrics: faithfulness, answer_relevancy, context_precision,
context_recall.

Also prints the CitationReport for every generated estimate: the Session 11
line-level citation-verification deliverable ("citation report on at least one
real estimate") falls out of this run for free.

Usage (host, stack up + OPENAI_API_KEY + at least the budgets collection
ingested)::

    uv run python scripts/eval_ragas_s11.py

Cost note: 5 queries x (1 reformulation call + 1 generation call, gpt-5 by
default) + RAGAS judge calls (4 metrics x 5 queries) + embeddings for
context_precision/context_recall. Real OpenAI spend — confirm before running.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

# ragas (as of 0.2.15, and still 0.4.x) unconditionally imports
# `langchain_community.chat_models.vertexai.ChatVertexAI` at package-import
# time. That submodule was removed once ChatVertexAI moved to the standalone
# `langchain-google-vertexai` package — we never use Vertex, so rather than
# pull in that whole integration just to satisfy a dead import, stub the
# module before `import ragas` runs.
if "langchain_community.chat_models.vertexai" not in sys.modules:
    _vertexai_stub = types.ModuleType("langchain_community.chat_models.vertexai")
    _vertexai_stub.ChatVertexAI = type("ChatVertexAI", (), {})
    sys.modules["langchain_community.chat_models.vertexai"] = _vertexai_stub

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
from langchain_openai import ChatOpenAI, OpenAIEmbeddings  # noqa: E402
from ragas import EvaluationDataset, SingleTurnSample, evaluate  # noqa: E402
from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import (  # noqa: E402
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

from scripts.s08_common import require_embedder  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.dependencies import get_runtime_retrieval_config, get_token_encoder  # noqa: E402
from app.generation.rag.context_assembler import (  # noqa: E402
    build_context_block,
    truncate_to_token_budget,
)
from app.generation.rag.estimator import generate_estimate  # noqa: E402
from app.generation.rag.query_reformulator import compose_search_text, reformulate_query  # noqa: E402
from app.generation.rag.retrieval.pipeline import retrieve  # noqa: E402
from app.generation.rag.schemas import Estimate  # noqa: E402
from app.generation.rag.validation import verify_citations  # noqa: E402

GOLDEN_PATH = ROOT / "evals" / "golden_generation_s11.json"
REPORT_PATH = ROOT / "evals" / "ragas_report_s11.md"

# Cheaper than GENERATION_MODEL (gpt-5): the judge only has to compare text, not
# derive an estimate, and 4 metrics x 5 queries adds up.
JUDGE_MODEL = "gpt-5-mini"

METRICS = [faithfulness, answer_relevancy, context_precision, context_recall]


def render_estimate_as_text(estimate: Estimate) -> str:
    """Flatten an Estimate into plain text — the RAGAS "answer" for one query."""
    if estimate.confidence == "insufficient":
        return f"Insufficient context: {estimate.insufficient_context_explanation}"

    lines = [
        f"Total: {estimate.total_engineer_days} engineer-days over {estimate.duration_weeks} weeks."
    ]
    for module in estimate.modules:
        lines.append(f"\n{module.name}:")
        for task in module.tasks:
            grounding = "grounded" if task.grounded else "assumption"
            lines.append(f"  - {task.name}: {task.engineer_days} engineer-days ({grounding})")
    for assumption in estimate.assumptions:
        lines.append(f"Assumption: {assumption.description} ({assumption.impact} impact)")
    lines.append(f"\nReasoning: {estimate.reasoning}")
    return "\n".join(lines)


async def _run_query(q: dict) -> tuple[SingleTurnSample, Estimate]:
    """Run the real pipeline for one golden query, return the RAGAS sample + estimate."""
    settings = get_settings()

    query = await reformulate_query(q["query"])
    search_text = compose_search_text(query)
    embedder = require_embedder()
    query_embedding = embedder.embed_one(search_text)

    runtime_retrieval = get_runtime_retrieval_config()
    retrieval = await retrieve(
        query_embedding=query_embedding,
        query_text=search_text,
        search_mode=runtime_retrieval.effective_search_mode(),
        rerank=runtime_retrieval.effective_rerank(),
        top_k=settings.RETRIEVAL_TOP_K,
        recall_k=settings.RETRIEVAL_RECALL_TOP_K,
        rerank_top_n=settings.RERANK_TOP_N,
        distance_threshold=settings.RETRIEVAL_DISTANCE_THRESHOLD,
        rrf_k=settings.RRF_K,
    )

    encoder = get_token_encoder()
    kept = truncate_to_token_budget(retrieval.chunks, settings.MAX_CONTEXT_TOKENS, encoder)
    context_block = build_context_block(kept)

    estimate = await generate_estimate(context_block, structured_query=query)
    report = verify_citations(estimate, kept)
    print(f"\n[{q['id']}] citation report: {report.model_dump()}")

    sample = SingleTurnSample(
        user_input=q["query"],
        response=render_estimate_as_text(estimate),
        retrieved_contexts=[chunk.content for chunk in kept] or ["(no chunks retrieved)"],
        reference=q["ground_truth"],
    )
    return sample, estimate


def _write_report(df: pd.DataFrame, ids: list[str]) -> None:
    metric_cols = [m.name for m in METRICS]
    df = df.copy()
    df.insert(0, "query", ids)

    lines = ["# RAGAS generation-quality baseline (Session 11)", ""]
    header = ["Query", *metric_cols]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for _, row in df.iterrows():
        cells = [row["query"]] + [f"{row[c]:.3f}" for c in metric_cols]
        lines.append("| " + " | ".join(cells) + " |")
    mean_row = ["**mean**"] + [f"{df[c].mean():.3f}" for c in metric_cols]
    lines.append("| " + " | ".join(mean_row) + " |")
    lines.append("")
    lines.append(
        "<!-- Add the 2-3 sentence note on what stands out here after reviewing the real numbers. -->"
    )

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {REPORT_PATH}")


async def main() -> int:
    get_settings()
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    queries = golden["queries"]

    samples = []
    for q in queries:
        sample, _estimate = await _run_query(q)
        samples.append(sample)

    settings = get_settings()
    llm = LangchainLLMWrapper(ChatOpenAI(model=JUDGE_MODEL, api_key=settings.OPENAI_API_KEY))
    embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(model=settings.EMBEDDING_MODEL, api_key=settings.OPENAI_API_KEY)
    )

    dataset = EvaluationDataset(samples=samples)
    result = evaluate(dataset=dataset, metrics=METRICS, llm=llm, embeddings=embeddings)

    df = result.to_pandas()
    _write_report(df, [q["id"] for q in queries])
    # The console codepage (e.g. Windows cp1252) can choke on stray unicode in
    # the LLM output; the report file is already written, so degrade gracefully.
    print(df.to_string().encode(sys.stdout.encoding or "utf-8", errors="replace").decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
