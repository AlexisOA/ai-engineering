"""CLI runner for the Session 6 CAG stress test.

For every ``(scenario, attachment_size_kb)`` cell, runs ``--repeats``
independent conversations against a live estimator and writes one CSV row
per turn. Each cell is an independent session, so cells run concurrently
(bounded by ``--concurrency``); turns *within* a cell are strictly
sequential because each depends on the session state the previous turn
left behind.

The two exercise axes are deliberately decoupled into two invocations
rather than one big cross product — Bloque 2 (multi-turn drift/cost) needs
real conversation depth; Bloque 3 (attachment size) is explicitly "run the
same initial estimation" per size, i.e. one turn. Crossing both at full
depth multiplies real-LLM turns (and OpenAI rate-limit exposure) for no
extra signal on either axis::

    # Axis 1: memory drift + cost-per-turn, no attachment noise.
    uv run python -m evals.stress.run \\
        --http http://localhost:8000 \\
        --scenarios growing,pivot,contradiction \\
        --attachment-sizes 0 \\
        --repeats 3 \\
        --output evals/stress/results.csv

    # Axis 2: latency/cost vs attachment size, single turn per size.
    uv run python -m evals.stress.run \\
        --http http://localhost:8000 \\
        --scenarios growing \\
        --attachment-sizes 5,20,50,100 \\
        --repeats 3 \\
        --max-turns 1 \\
        --output evals/stress/results.csv \\
        --append

Only ``--http`` mode is supported: this exercise measures a real, running
estimator (real LLM, real PDFs), not the in-process test double the golden
eval suite uses for CI speed.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from pathlib import Path
from typing import Any

import httpx

from app.schemas.estimation import TurnObservation
from evals.stress.fixtures.build_pdfs import fixture_path
from evals.stress.metrics import CostBudgetMetric, LatencyBudgetMetric, MemoryDriftMetric
from evals.stress.scenarios import get_scenario

# ``scenario_turn`` is this cell's 1-based request count — it always
# advances, and it's what determines which scripted fact/content the
# runner just sent (so "does the turn-3 fact still show up" means turn-3
# by this column). ``turn_index`` is the server's own count of turns the
# session actually *completed* (``Session.turn_count``, from
# ``TurnObservation``) — it does not advance on a failed turn (the LLM
# call never reaches history.append), so once any turn in a cell fails,
# the two columns diverge. Both are kept: scenario_turn anchors "what was
# sent", turn_index anchors "how much context has the session actually
# accumulated".
CSV_COLUMNS = [
    "scenario",
    "attachment_size_kb",
    "repeat",
    "scenario_turn",
    "turn_index",
    "session_id",
    "enriched_transcript_chars",
    "attachments_total_chars",
    "messages_in_window",
    "anchors_count",
    "summary_chars",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "latency_ms",
    "cache_hit_kind",
    "last_resolved_tier",
    "cumulative_cost_usd",
    "latency_budget_pass",
    "cost_budget_pass",
    "memory_drift_fact",
    "memory_drift_pass",
    "http_status",
]

# Held constant across every turn/cell so the only thing that varies between
# rows is what the exercise is actually measuring (scenario, attachment
# size, turn depth) — mixing project types or output formats would confound
# the curves.
_PROJECT_TYPE = "web_saas"
_DETAIL_LEVEL = "medium"
_OUTPUT_FORMAT = "phases_table"


async def _run_cell(
    client: httpx.AsyncClient,
    *,
    scenario_name: str,
    attachment_size_kb: int,
    repeat: int,
    latency_metric: LatencyBudgetMetric,
    cost_metric: CostBudgetMetric,
    max_turns: int | None = None,
) -> list[dict[str, Any]]:
    scenario = get_scenario(scenario_name)
    turns = scenario.turns[:max_turns] if max_turns else scenario.turns

    try:
        create = await client.post("/sessions")
        create.raise_for_status()
        session_id = create.json()["session_id"]
    except httpx.HTTPError as exc:
        return [
            {
                "scenario": scenario_name,
                "attachment_size_kb": attachment_size_kb,
                "repeat": repeat,
                "turn_index": 0,
                "session_id": "",
                "http_status": f"error:{type(exc).__name__}",
            }
        ]

    rows: list[dict[str, Any]] = []
    cumulative_cost = 0.0
    current_fact: str | None = None
    current_fact_field = "any"

    for turn_number, turn in enumerate(turns, start=1):
        data = {
            "transcript": turn.transcript,
            "project_type": _PROJECT_TYPE,
            "detail_level": _DETAIL_LEVEL,
            "output_format": _OUTPUT_FORMAT,
        }
        files = None
        if turn_number == 1 and attachment_size_kb > 0:
            pdf_bytes = fixture_path(attachment_size_kb).read_bytes()
            files = {
                "attachments": (
                    f"attach_{attachment_size_kb}kb.pdf",
                    pdf_bytes,
                    "application/pdf",
                )
            }

        # A single flaky/slow turn (timeout, connection reset, 5xx) must not
        # take down the whole sweep — record it as an error row and move on
        # to the next cell. The session itself may be unusable after this,
        # so we stop walking turns for this cell rather than pretend to
        # continue a conversation with a gap in it.
        try:
            response = await client.post(
                f"/sessions/{session_id}/estimate", data=data, files=files
            )
            http_status = response.status_code
        except httpx.HTTPError as exc:
            rows.append(
                {
                    "scenario": scenario_name,
                    "attachment_size_kb": attachment_size_kb,
                    "repeat": repeat,
                    "turn_index": turn_number,
                    "session_id": session_id,
                    "http_status": f"error:{type(exc).__name__}",
                }
            )
            break

        if http_status != 200:
            rows.append(
                {
                    "scenario": scenario_name,
                    "attachment_size_kb": attachment_size_kb,
                    "repeat": repeat,
                    "scenario_turn": turn_number,
                    "session_id": session_id,
                    "http_status": http_status,
                }
            )
            continue

        payload = response.json()
        observation = TurnObservation.model_validate(payload["observation"])
        cumulative_cost += observation.cost_usd

        if turn.fact:
            current_fact = turn.fact
            current_fact_field = turn.fact_field or "any"

        memory_drift_pass: bool | None = True
        if current_fact is not None:
            try:
                snapshot_resp = await client.get(f"/sessions/{session_id}")
                snapshot_resp.raise_for_status()
                drift = MemoryDriftMetric(
                    fact=current_fact, fact_field=current_fact_field
                ).evaluate(snapshot_resp.json())
                memory_drift_pass = drift.passed
            except httpx.HTTPError:
                memory_drift_pass = None

        latency_result = latency_metric.evaluate(observation)
        cost_result = cost_metric.evaluate(observation)

        rows.append(
            {
                "scenario": scenario_name,
                "attachment_size_kb": attachment_size_kb,
                "repeat": repeat,
                "scenario_turn": turn_number,
                "turn_index": observation.turn_index,
                "session_id": session_id,
                "enriched_transcript_chars": observation.enriched_transcript_chars,
                "attachments_total_chars": observation.attachments_total_chars,
                "messages_in_window": observation.messages_in_window,
                "anchors_count": observation.anchors_count,
                "summary_chars": observation.summary_chars,
                "tokens_in": observation.tokens_in,
                "tokens_out": observation.tokens_out,
                "cost_usd": observation.cost_usd,
                "latency_ms": observation.latency_ms,
                "cache_hit_kind": observation.cache_hit_kind,
                "last_resolved_tier": observation.last_resolved_tier,
                "cumulative_cost_usd": round(cumulative_cost, 6),
                "latency_budget_pass": latency_result.passed,
                "cost_budget_pass": cost_result.passed,
                "memory_drift_fact": current_fact or "",
                "memory_drift_pass": memory_drift_pass,
                "http_status": http_status,
            }
        )
    return rows


async def _run_all(
    *,
    base_url: str,
    scenarios: list[str],
    attachment_sizes: list[int],
    repeats: int,
    concurrency: int,
    latency_budget_ms: int,
    cost_budget_usd: float,
    output: Path,
    append: bool = False,
    max_turns: int | None = None,
) -> list[dict[str, Any]]:
    """Run every cell and flush its rows to ``output`` as soon as the cell
    finishes — real-LLM sweeps take long enough that losing everything to
    one late failure, or having zero visibility until the very end, would
    make them impractical to babysit. ``append`` lets a second invocation
    (e.g. the attachment-size axis) land in the same CSV as a first one
    (e.g. the multi-turn scenario axis) without clobbering it."""
    latency_metric = LatencyBudgetMetric(budget_ms=latency_budget_ms)
    cost_metric = CostBudgetMetric(budget_usd=cost_budget_usd)
    semaphore = asyncio.Semaphore(concurrency)

    output.parent.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, Any]] = []
    write_header = not (append and output.exists() and output.stat().st_size > 0)
    mode = "a" if append else "w"

    with output.open(mode, newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        if write_header:
            writer.writeheader()
        fh.flush()

        async with httpx.AsyncClient(base_url=base_url, timeout=180.0) as client:

            async def _bounded_cell(scenario_name: str, size_kb: int, repeat: int):
                async with semaphore:
                    return await _run_cell(
                        client,
                        scenario_name=scenario_name,
                        attachment_size_kb=size_kb,
                        repeat=repeat,
                        latency_metric=latency_metric,
                        cost_metric=cost_metric,
                        max_turns=max_turns,
                    )

            cells = [
                (scenario_name, size_kb, repeat)
                for scenario_name in scenarios
                for size_kb in attachment_sizes
                for repeat in range(1, repeats + 1)
            ]
            tasks = [asyncio.ensure_future(_bounded_cell(*cell)) for cell in cells]
            print(f"Running {len(tasks)} cells (scenario x size x repeat), concurrency={concurrency}")

            done = 0
            for task in asyncio.as_completed(tasks):
                cell_rows = await task
                for row in cell_rows:
                    writer.writerow({col: row.get(col, "") for col in CSV_COLUMNS})
                    all_rows.append(row)
                fh.flush()
                done += 1
                print(f"  cell {done}/{len(tasks)} done ({len(cell_rows)} rows written)")

    return all_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http", required=True, help="Base URL, e.g. http://localhost:8000")
    parser.add_argument("--scenarios", default="growing,pivot,contradiction")
    parser.add_argument("--attachment-sizes", default="0,5,20,50,100")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--latency-budget-ms", type=int, default=8000)
    parser.add_argument("--cost-budget-usd", type=float, default=0.02)
    parser.add_argument("--output", type=Path, default=Path("evals/stress/results.csv"))
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to --output instead of overwriting (for a second, decoupled axis).",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Truncate every scenario to at most this many turns (e.g. 1 for a single-turn probe).",
    )
    args = parser.parse_args()

    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    attachment_sizes = [int(s.strip()) for s in args.attachment_sizes.split(",") if s.strip()]

    rows = asyncio.run(
        _run_all(
            base_url=args.http,
            scenarios=scenarios,
            attachment_sizes=attachment_sizes,
            repeats=args.repeats,
            concurrency=args.concurrency,
            latency_budget_ms=args.latency_budget_ms,
            cost_budget_usd=args.cost_budget_usd,
            output=args.output,
            append=args.append,
            max_turns=args.max_turns,
        )
    )

    error_rows = sum(1 for r in rows if r.get("http_status") != 200)
    print(f"\nWrote {len(rows)} rows to {args.output} ({error_rows} errored turns)")
    return 0 if error_rows == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
