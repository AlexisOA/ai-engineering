# CAG Stress Test — Report

Empirical map of where this CAG breaks, from a real run (real `gpt-4o-mini`
calls, real synthetic PDFs) against the estimator built through Session 5.

**Scope note on the run design.** The exercise's own "done" criteria allow
"adjusting the floors to reach the minimum" on the turn count — the 3
scenarios x 5 sizes x >=3 repeats structure is what's fixed, not a full
20-turn depth for every cell. Given real wall-clock and OpenAI rate-limit
constraints, this run splits the two axes instead of crossing them at full
depth:

- **Axis 1** (memory drift + cost/latency vs conversation depth): all 3
  scenarios, size=0 only (no attachment noise), 3 repeats, 9 turns each.
- **Axis 2** (latency/cost vs attachment size): the exercise's own wording
  for Bloque 3 is "run the same initial estimation" per size — a single
  turn, not a full conversation — so this axis is the `growing` scenario's
  first turn only, across all 4 non-zero sizes, 3 repeats.

**Run parameters used:**

| Setting               | Value                                          |
|-----------------------|-------------------------------------------------|
| Model                 | `gpt-4o-mini` (PRIMARY_MODEL — switched from the repo's default `gpt-4o` to keep this run's cost/latency bounded) |
| Scenarios             | growing, pivot, contradiction                    |
| Attachment sizes (KB) | 0 (axis 1), 5/20/50/100 (axis 2)                 |
| Turns per cell        | 9 (axis 1), 1 (axis 2)                           |
| Repeats per cell      | 3                                                |
| Latency budget        | 8000 ms                                          |
| Cost budget per turn  | $0.02                                            |
| Total turns observed  | 93 rows in `results.csv` (81 axis 1 + 12 axis 2) |
| Total LLM spend       | ~$0.12 across all successful turns               |

---

## 1. Summary table

One row per `(scenario, attachment_size_kb)` cell, pooled across the 3 repeats.

| Scenario       | KB  | n  | ok | err | err % | P50 ms | P95 ms |
|----------------|----:|---:|---:|----:|------:|-------:|-------:|
| growing        |   0 | 27 | 22 |   5 |  18.5 |   7163 |   9808 |
| pivot          |   0 | 27 | 15 |  12 |  44.4 |   9551 |  27005 |
| contradiction  |   0 | 27 | 20 |   7 |  25.9 |   1973 |  16816 |
| growing        |   5 |  3 |  2 |   1 |  33.3 |  19496 |  28571 |
| growing        |  20 |  3 |  2 |   1 |  33.3 |   4585 |   7143 |
| growing        |  50 |  3 |  1 |   2 |  66.7 |   7587 |      — |
| growing        | 100 |  3 |  2 |   1 |  33.3 |   7312 |   9115 |

`err` is exclusively `InstructorRetryException` (HTTP 502): the LLM never
produced `phases_sum == total_cost_eur` within 6 retries. There is no
other failure mode in this run — no timeouts, no guardrail rejections.

Attachment-axis `n` is small (2-3 ok per cell) because the axis is
single-turn by design — read the latency numbers there as a rough signal,
not a tight estimate. `attachments_total_chars` at 100 KB landed at exactly
60000 in every row, confirming the `MAX_ATTACHMENT_CHARS` truncation fires
as designed.

---

## 2. Three curves (as tables)

### 2a. Latency vs context size

`tokens_in` is the cleanest proxy for how much context the model swallowed
this turn. Bucket by `tokens_in` (axis 1, all scenarios pooled), median
latency:

| `tokens_in` bucket | Median latency (ms) | n  |
|--------------------|---------------------:|---:|
| 1000–2999          |                 1691 | 12 |
| 3000–6999          |                 4701 | 22 |
| 7000–14999         |                 8786 | 17 |
| 15000+             |                16816 |  6 |

Clean monotonic curve: latency roughly doubles every time `tokens_in`
roughly doubles, from ~1.7s at ~2K tokens to ~16.8s past 15K tokens (max
observed: 41706 tokens_in). Past ~7K tokens the median already exceeds
this run's 8000ms budget.

### 2b. Cost accumulated vs scenario turn (per scenario, size = 0)

Average `cumulative_cost_usd` across repeats, by the scenario's own turn
position (`scenario_turn` — see the note in section 5 on why this differs
from `turn_index`):

| Turn | growing $ | pivot $ | contradiction $ |
|-----:|----------:|--------:|-----------------:|
|    1 |    0.0022 |  0.0043 |            0.0011 |
|    3 |    0.0041 |    —    |            0.0004 |
|    5 |    0.0058 |  0.0122 |            0.0012 |
|    7 |    0.0074 |  0.0152 |            0.0033 |
|    9 |    0.0093 |  0.0162 |            0.0054 |

`growing` and `pivot` both show a roughly linear-to-superlinear climb —
`pivot` costs ~7x more by turn 9 than `growing`'s turn 1, consistent with
every turn re-sending the full sliding-window history plus the growing
summary. `contradiction`'s curve is lower and noisier because more of its
early turns errored (no cost charged on a 502), not because the underlying
per-turn cost is actually cheaper.

### 2c. Memory drift pass rate, by scenario (size = 0)

Case-insensitive presence check against the `GET /sessions/{id}` snapshot,
using the `fact_field` each scenario declares:

| Scenario      | Fact tracked                          | Field checked | Checks | Pass rate |
|---------------|----------------------------------------|----------------|-------:|----------:|
| growing       | `project_name` = "Project Nimbus"      | `project_name` |     15 |    100.0% |
| pivot         | `project_name`, then `Flutter`         | `project_name`/`technologies` | 13 | 100.0% |
| contradiction | `project_name`, then "30000 EUR"/"80000 EUR" | `project_name`/`scope` | 20 | 30.0% |

`project_name` never drops in any scenario through turn 9 — the metadata
extractor re-derives it every turn and it is a short, unambiguous string.
The contradiction scenario's 30.0% overall pass rate is entirely explained
by one sub-finding: **every single check against the budget figure
(`agreed_scope`) failed — 0/14 — in both repeats that reached the
budget-introducing turns.** `ProjectMetadata.agreed_scope` never once
contained "30000 EUR" or "80000 EUR" after they were stated; the
extractor evidently doesn't route monetary figures into that field. This
run only checked the structured `agreed_scope` field, so it can't tell
whether the number survives elsewhere (raw summary text, a different
metadata field) — see the claims in section 4.

---

## 3. Reading: where the CAG starts to break

**Paragraph 1 — the dominant failure mode.** In this run the CAG's most
common failure isn't slow degradation, it's a hard wall: 24/81 axis-1
turns (30%) and 5/12 axis-2 turns (42%) hit `InstructorRetryException` —
the LLM could not make `phases_sum == total_cost_eur` add up within 6
retries, so the endpoint returns a 502 and that turn contributes zero data.
`pivot` is worst hit (44% error rate) — the mid-conversation stack switch
apparently makes the arithmetic-with-history task harder for
`gpt-4o-mini`, not just the raw context length (`contradiction`, which
also grows the history, errors less: 26%). Where turns *do* succeed,
latency scales cleanly and predictably with `tokens_in` (section 2a) —
p50 jumps from 1.7s to 16.8s across the observed context-size range, blowing
past the 8s budget once `tokens_in` exceeds ~7000.

**Paragraph 2 — what this implies for the RAG decision.** Two distinct,
independent failure modes showed up, and RAG addresses only one of them.
The `agreed_scope` field losing the budget figure 100% of the time
(section 2c) is a metadata-extraction bug, not a context-size problem —
switching to RAG doesn't fix an extractor that never routes monetary
values into the right field; that needs a schema/prompt fix regardless of
retrieval strategy. What RAG *does* address is the latency curve: if
retrieval keeps `tokens_in` in the 1-3K range instead of letting the raw
history balloon past 15K, the p50 stays under ~2s instead of climbing to
~17s — matching the "flatten the curve" argument from the exercise brief.
It would not, on its own, fix the 502 arithmetic-failure rate, since that
failure is about the *model's* reasoning under Instructor's retry loop,
not about what context it was given.

---

## 4. Four claims to defend

1. My CAG's dominant failure in this run is a **hard failure** (502 from
   exhausted `phases_sum` validation retries), not silent degradation —
   24/81 axis-1 turns (30%) and worst in `pivot` (44%), because switching
   the stack mid-conversation makes the arithmetic task harder for
   `gpt-4o-mini` than pure accumulation does.
2. Cost per successful turn grows roughly linearly with turn depth within
   this 9-turn window (`growing`: $0.0022 -> $0.0093, ~4.2x; `pivot`:
   $0.0043 -> $0.0162, ~3.8x) because every turn re-sends the full sliding
   window (up to `MAX_CONVERSATION_TURNS=6` pairs) plus the cumulative
   summary, not just the new user message.
3. The dominant latency bottleneck is **tokens_in**, not attachment size
   specifically: the tokens_in-bucketed curve (1.7s -> 16.8s) is clean and
   monotonic, while the attachment-size curve is noisy at this sample size
   (n=2-3/cell) — attachments contribute to tokens_in, but conversation
   history at turn 9 already pushes some `growing`/`pivot` turns past
   15K tokens on its own, no attachment required.
4. To cut context by 50% without losing recall, I'd attack the **raw
   sliding-window history**, not the cumulative summary or anchors: the
   `project_name` fact (which the summarizer/anchors are responsible for
   preserving long-term) has 100% recall through turn 9 pooled across all
   3 scenarios, while the biggest cost/latency driver is the up-to-6-pair
   verbatim window riding along every turn (section 2b's near-linear
   cost growth). The 0% recall on `agreed_scope`'s budget figure is a
   separate, extraction-logic problem this run isolated but that trimming
   context would not fix.

---

## 5. Reproducibility

The two axes are run as separate, decoupled invocations rather than one
big cross product (see the scope note at the top) — `--append` lands the
second axis in the same CSV as the first:

```bash
# Rebuild the fixtures (deterministic; same paragraph, same byte counts).
uv run python -m evals.stress.fixtures.build_pdfs

# Real run against a live estimator.
docker compose up --build -d
curl -sf http://localhost:8000/health

# Axis 1: memory drift + cost/latency vs conversation depth (size=0 only).
uv run python -m evals.stress.run \
    --http http://localhost:8000 \
    --scenarios growing,pivot,contradiction \
    --attachment-sizes 0 \
    --repeats 3 \
    --latency-budget-ms 8000 \
    --cost-budget-usd 0.02 \
    --output evals/stress/results.csv

# Axis 2: latency/cost vs attachment size (single turn per size), appended.
uv run python -m evals.stress.run \
    --http http://localhost:8000 \
    --scenarios growing \
    --attachment-sizes 5,20,50,100 \
    --repeats 3 \
    --max-turns 1 \
    --latency-budget-ms 8000 \
    --cost-budget-usd 0.02 \
    --output evals/stress/results.csv \
    --append

# Quick sanity check.
wc -l evals/stress/results.csv          # >= 50 rows + header
head -1 evals/stress/results.csv        # 23-column schema
```

Note: `--concurrency` above defaults to 4, which drove heavy OpenAI
rate-limit contention (429s) in earlier attempts at this run's scale —
`--concurrency 2` avoided that.

The CSV has two turn-count columns: `scenario_turn` is the request's
1-based position in the scenario script (what content/fact was actually
sent that turn — always advances, even through failures); `turn_index` is
`Session.turn_count`, the server's count of turns that *succeeded* (it
does not advance on a 502, since the LLM call never reaches
`history.append`). Section 2b groups by `scenario_turn` because it's
what determines which fact should be in play; `turn_index` is the more
honest x-axis for "how much context has this session actually
accumulated," and the two diverge as soon as any turn in a cell fails.

The `results.csv` produced is gitignored (regenerated per run). This
`REPORT.md` is the artefact that ships to the directo.
