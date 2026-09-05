#!/usr/bin/env python3
"""RAGAS generation-quality baseline (Session 11) — LOCAL-EMBEDDINGS + CLAUDE FALLBACK.

DEVIATION FROM THE REAL PIPELINE, documented (not hidden): the org's OpenAI
credit balance was exhausted (confirmed via ``models.list`` [ok],
``chat.completions`` [429 credit_balance_exhausted] and ``embeddings`` [same])
the day this had to ship. Every OpenAI-dependent piece is swapped for a
same-shape substitute so the numbers below are REAL measurements of a REAL
(if temporary) pipeline, not invented figures:

* Embeddings: ``text-embedding-3-small`` (OpenAI) -> ``all-MiniLM-L6-v2``
  (sentence-transformers, local, ~90MB, CPU). The production pgvector corpus
  is embedded with the OpenAI model and is NOT touched or reused here — this
  script re-chunks ``data/budgets_sample.json`` with the REAL structural
  chunker (``app.generation.rag.chunking.structural``) and does a small
  in-memory cosine top-k search (17 budgets, ~60 chunks: trivial, no DB
  writes, no new infra).
* Reformulation + generation + RAGAS judge: OpenAI models -> Anthropic Claude,
  via the SAME ``LLMWrapper`` (Instructor + LiteLLM) the production path uses
  — confirmed working with ``model_override="claude-*"``. The one real
  incompatibility: ``generate_estimate()`` hardcodes
  ``reasoning_effort=settings.GENERATION_REASONING_EFFORT`` for the gpt-5
  family, which litellm maps to Claude's "thinking" — thinking is rejected
  together with Instructor's forced tool_choice. So generation here calls
  ``wrapper.complete_structured`` directly (same prompt builders, same
  ``Estimate`` schema and validators, same ``verify_citations``), just
  without that gpt-5-only parameter.

Everything else — schema, prompts, context assembly, token truncation,
citation verification, the golden set — is the real Session 11 code, unchanged.

Once the org's OpenAI credit is restored, ``scripts/eval_ragas_s11.py`` (the
non-fallback script) should be re-run for the canonical numbers; this file
stays as a documented one-off, not the primary deliverable path.

Usage: ``uv run python scripts/eval_ragas_s11_fallback.py`` (no docker/DB
service required beyond what ``app.config`` needs to import; ANTHROPIC_API_KEY
must be set).
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

if "langchain_community.chat_models.vertexai" not in sys.modules:
    _vertexai_stub = types.ModuleType("langchain_community.chat_models.vertexai")
    _vertexai_stub.ChatVertexAI = type("ChatVertexAI", (), {})
    sys.modules["langchain_community.chat_models.vertexai"] = _vertexai_stub

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from langchain_anthropic import ChatAnthropic  # noqa: E402
from langchain_core.embeddings import Embeddings  # noqa: E402
from ragas import EvaluationDataset, SingleTurnSample, evaluate  # noqa: E402
from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import (  # noqa: E402
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)
from sentence_transformers import SentenceTransformer  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.dependencies import get_llm_wrapper, get_token_encoder  # noqa: E402
from app.generation.rag.chunking.structural import JSONStructuralChunker  # noqa: E402
from app.generation.rag.context_assembler import (  # noqa: E402
    build_context_block,
    truncate_to_token_budget,
)
from app.generation.rag.prompt_builder import build_system_prompt, build_user_message  # noqa: E402
from app.generation.rag.query_reformulator import compose_search_text, reformulate_query  # noqa: E402
from app.generation.rag.schemas import Budget, Estimate, RetrievedChunk  # noqa: E402
from app.generation.rag.validation import verify_citations  # noqa: E402
from scripts.eval_ragas_s11 import render_estimate_as_text  # noqa: E402

GOLDEN_PATH = ROOT / "evals" / "golden_generation_s11.json"
BUDGETS_PATH = ROOT / "data" / "budgets_sample.json"
REPORT_PATH = ROOT / "evals" / "ragas_report_s11.md"

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
REFORMULATION_MODEL = "claude-haiku-4-5"
# Haiku, not Sonnet: a thorough module->task Estimate over a large context block
# pushed Sonnet past a 90s timeout on some queries. Haiku is fast enough to finish
# reliably; this is a one-off fallback run, not the canonical numbers.
GENERATION_MODEL = "claude-haiku-4-5"
JUDGE_MODEL = "claude-haiku-4-5"
TOP_K = 8

METRICS = [faithfulness, answer_relevancy, context_precision, context_recall]


class LocalEmbeddings(Embeddings):
    """Minimal langchain Embeddings adapter over a local sentence-transformers model."""

    def __init__(self, model: SentenceTransformer) -> None:
        self._model = model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, convert_to_numpy=True).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self._model.encode([text], convert_to_numpy=True)[0].tolist()


def _load_corpus_chunks() -> tuple[list[RetrievedChunk], np.ndarray]:
    """Chunk the real budgets corpus (structural chunker) and embed locally."""
    raw = json.loads(BUDGETS_PATH.read_text(encoding="utf-8"))
    budgets = [Budget.model_validate(b) for b in raw]
    chunks = JSONStructuralChunker().chunk(budgets)

    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    embeddings = model.encode([c.text for c in chunks], convert_to_numpy=True, normalize_embeddings=True)

    retrieved = [
        RetrievedChunk(
            id=idx,
            content=chunk.text,
            sector=chunk.metadata.get("client_sector", "unknown"),
            project_year=chunk.metadata.get("year", 0),
            chunk_type="budget_component",
            distance=0.0,  # placeholder — replaced per-query below
            budget_id=chunk.metadata.get("budget_id"),
            source_id=chunk.metadata.get("budget_id"),
            estimated_hours=chunk.metadata.get("estimated_hours"),
        )
        for idx, chunk in enumerate(chunks)
    ]
    return retrieved, embeddings, model


def _top_k(
    query_text: str, chunks: list[RetrievedChunk], corpus_embeddings: np.ndarray, model: SentenceTransformer
) -> list[RetrievedChunk]:
    """Brute-force cosine top-k over the small local corpus (~60 chunks)."""
    query_vec = model.encode([query_text], convert_to_numpy=True, normalize_embeddings=True)[0]
    similarities = corpus_embeddings @ query_vec
    order = np.argsort(-similarities)[:TOP_K]
    ranked = []
    for i in order:
        chunk = chunks[i]
        ranked.append(chunk.model_copy(update={"distance": float(1.0 - similarities[i])}))
    return ranked


async def _generate_with_claude(context_block: str, query) -> Estimate:
    """Same prompt/schema as generate_estimate(), without the gpt-5-only reasoning_effort."""
    wrapper = get_llm_wrapper()
    user_message = build_user_message(context_block, query)
    estimate, _meta = await asyncio.to_thread(
        wrapper.complete_structured,
        system_prompt=build_system_prompt(include_hours=True),
        user_message=user_message,
        response_model=Estimate,
        model_override=GENERATION_MODEL,
        max_tokens=8000,
        max_retries=6,
    )
    return estimate


async def _run_query(q: dict, chunks: list[RetrievedChunk], corpus_embeddings, embed_model) -> SingleTurnSample:
    settings = get_settings()
    query = await reformulate_query(q["query"])
    search_text = compose_search_text(query)

    ranked = _top_k(search_text, chunks, corpus_embeddings, embed_model)
    encoder = get_token_encoder()
    kept = truncate_to_token_budget(ranked, settings.MAX_CONTEXT_TOKENS, encoder)
    context_block = build_context_block(kept)

    estimate = await _generate_with_claude(context_block, query)
    report = verify_citations(estimate, kept)
    print(f"\n[{q['id']}] citation report: {report.model_dump()}")

    return SingleTurnSample(
        user_input=q["query"],
        response=render_estimate_as_text(estimate),
        retrieved_contexts=[c.content for c in kept] or ["(no chunks retrieved)"],
        reference=q["ground_truth"],
    )


def _write_report(df: pd.DataFrame, ids: list[str]) -> None:
    metric_cols = [m.name for m in METRICS]
    df = df.copy()
    df.insert(0, "query", ids)

    lines = [
        "# RAGAS generation-quality baseline (Session 11)",
        "",
        "**Methodology deviation (disclosed):** the org's OpenAI credit balance was "
        "exhausted (`models.list` ok, `chat.completions` and `embeddings` both "
        "429 `credit_balance_exhausted`, confirmed independently). This run uses "
        "`scripts/eval_ragas_s11_fallback.py`: local `all-MiniLM-L6-v2` embeddings "
        "over an in-memory re-chunk of `data/budgets_sample.json` (real structural "
        "chunker, brute-force cosine top-k, no DB writes) instead of the production "
        "pgvector index, and Anthropic Claude (via the same `LLMWrapper`) instead of "
        "GPT-5/GPT-5-mini for reformulation, generation and the RAGAS judge. The "
        "prompts, schema, validators and `verify_citations` are the real Session 11 "
        "code, unmodified. Re-run `scripts/eval_ragas_s11.py` once OpenAI credit is "
        "restored for the canonical (OpenAI embeddings + gpt-5) numbers.",
        "",
    ]
    header = ["Query", *metric_cols]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for _, row in df.iterrows():
        cells = [row["query"]] + [f"{row[c]:.3f}" for c in metric_cols]
        lines.append("| " + " | ".join(cells) + " |")
    mean_row = ["**mean**"] + [f"{df[c].mean():.3f}" for c in metric_cols]
    lines.append("| " + " | ".join(mean_row) + " |")
    lines.append("")
    lines.append("<!-- Add the 2-3 sentence note on what stands out here after reviewing the real numbers. -->")

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {REPORT_PATH}")


async def main() -> int:
    settings = get_settings()
    # reformulate_query() reads settings.REFORMULATION_MODEL internally (no override
    # param); point it at Claude for this run only (in-process, .env untouched).
    settings.REFORMULATION_MODEL = REFORMULATION_MODEL
    # The wrapper's 30s default (settings.LLM_TIMEOUT) is tuned for gpt-5-mini; a full
    # module->task Estimate from claude-sonnet takes longer over a large context block.
    get_llm_wrapper().timeout = 150
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    queries = golden["queries"]

    print(f"Loading local embedding model {EMBEDDING_MODEL_NAME} + chunking the corpus...")
    chunks, corpus_embeddings, embed_model = _load_corpus_chunks()
    print(f"{len(chunks)} chunks ready.")

    samples = []
    for q in queries:
        samples.append(await _run_query(q, chunks, corpus_embeddings, embed_model))

    settings = get_settings()
    llm = LangchainLLMWrapper(ChatAnthropic(model=JUDGE_MODEL, api_key=settings.ANTHROPIC_API_KEY))
    embeddings = LangchainEmbeddingsWrapper(LocalEmbeddings(embed_model))

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
