# RAGAS generation-quality baseline (Session 11)

**Methodology deviation (disclosed):** the org's OpenAI credit balance was exhausted (`models.list` ok, `chat.completions` and `embeddings` both 429 `credit_balance_exhausted`, confirmed independently). This run uses `scripts/eval_ragas_s11_fallback.py`: local `all-MiniLM-L6-v2` embeddings over an in-memory re-chunk of `data/budgets_sample.json` (real structural chunker, brute-force cosine top-k, no DB writes) instead of the production pgvector index, and Anthropic Claude (via the same `LLMWrapper`) instead of GPT-5/GPT-5-mini for reformulation, generation and the RAGAS judge. The prompts, schema, validators and `verify_citations` are the real Session 11 code, unmodified. Re-run `scripts/eval_ragas_s11.py` once OpenAI credit is restored for the canonical (OpenAI embeddings + gpt-5) numbers.

| Query | faithfulness | answer_relevancy | context_precision | context_recall |
| --- | --- | --- | --- | --- |
| Q1 | 0.031 | 0.666 | 1.000 | 0.750 |
| Q2 | 0.136 | 0.671 | 1.000 | 0.667 |
| Q3 | 0.057 | 0.488 | 0.333 | 0.500 |
| Q4 | 0.071 | 0.807 | 1.000 | 0.833 |
| Q5 | 0.069 | 0.650 | 1.000 | 0.500 |
| **mean** | 0.073 | 0.656 | 0.867 | 0.650 |

## What stands out

`faithfulness` is strikingly low (mean 0.073) despite `verify_citations` reporting almost no
dangling citations across all five estimates — the two are measuring different things: citing a
real, retrieved chunk id is not the same as every *natural-language claim* in the rendered answer
being entailed by that chunk's text. Most "grounded" tasks carry an LLM-*inferred* `engineer_days`
number that never appears verbatim in the source (the source only has raw historical hours), so
RAGAS's claim-decomposition flags those derived numbers as unsupported — coarse citation was
hiding exactly this gap, which is the diagnosis this exercise set out to make. `context_precision`
is strong everywhere except Q3 (0.333, telemedicine): BUD-2024-010 (remote monitoring) is a
same-sector but functionally-adjacent analog by the golden set's own annotation, and the retriever
pulled enough of it in to visibly hurt precision on that one query.
