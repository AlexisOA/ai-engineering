#!/usr/bin/env python3
"""Session 14 — run the supervisor + specialists estimation graph end to end.

Drives the compiled ``StateGraph`` (``app/domain/graph/supervisor``) through the
full agent pipeline:

    supervisor → requirements_extractor → supervisor → budget_searcher →
    supervisor → estimate_generator → supervisor → coherence_validator →
    supervisor → human_review_gate → [PAUSE if untrustworthy] → END

By default AUTO-APPROVES the human gate with a canned decision so a whole run
completes without a person in the loop; pass ``--no-auto-resume`` to stop after
the first pause and inspect the persisted checkpoint by hand.

Persistence: opens the SAME Postgres the project uses (pgvector) as the
checkpointer by default; pass ``--memory`` for an in-process ``MemorySaver``.

Windows gotcha (same as ``run_graph_s13.py``'s documented one): ``psycopg``'s
async mode cannot run on the default ``ProactorEventLoop``. This script sets
``WindowsSelectorEventLoopPolicy`` at import time on ``win32`` — scoped to this
standalone process only, never applied globally in ``app/main.py`` (that
destabilised the wider pytest suite when tried — see ARCHITECTURE notes).

Run::

    # Deliverable run: real retrieval + gpt models + Postgres checkpointer
    uv run python scripts/run_supervisor_s14.py \\
        --out exercises/session-14/example_run_edge_case_own.txt

    # Offline smoke: in-process checkpointer, still needs an LLM key
    uv run python scripts/run_supervisor_s14.py --memory
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from langgraph.types import Command  # noqa: E402

from app.domain.graph.supervisor.build import build_supervisor_graph  # noqa: E402

DEFAULT_TRANSCRIPT = REPO_ROOT / "exercises" / "session-14" / "sample_transcript_edge_case.txt"

# Canned decision fed to the human gate on auto-resume.
_AUTO_DECISION = {
    "approved": True,
    "status": "needs_review",  # honest: a human accepted it despite the low confidence
    "notes": "Reviewed manually: no historical precedent for this hardware/mainframe combo.",
}


def _render(state: dict) -> str:
    lines = [
        "=" * 78,
        "SESSION 14 — SUPERVISOR + SPECIALISTS ESTIMATION GRAPH RUN",
        "=" * 78,
        f"status     : {state.get('status')}",
        f"confidence : {state.get('confidence')}",
        "",
        "REQUIREMENTS (requirements_extractor)",
    ]
    for r in state.get("requirements") or []:
        lines.append(f"  - {r}")

    lines += ["", "COMPONENTS + BUDGET MATCHES (budget_searcher)"]
    matches_by_component: dict[str, list[dict]] = {}
    for m in state.get("budget_matches") or []:
        matches_by_component.setdefault(m["component"], []).append(m)
    for c in state.get("components") or []:
        name = c["name"]
        matches = matches_by_component.get(name, [])
        lines.append(f"  - {name} [{c['category']}]")
        if matches:
            for m in matches:
                lines.append(f"      - {m['amount']}h @ distance {m['distance']:.3f}")
        else:
            lines.append("      (no historical precedent found)")

    lines += ["", "ESTIMATE (estimate_generator)"]
    estimate = state.get("estimate") or {}
    for c in estimate.get("components") or []:
        days = c.get("engineer_days")
        days_text = f"{days}d" if days is not None else "UNGROUNDED"
        lines.append(f"  - {c['name']}: {days_text}  ({c.get('rationale')})")
    lines.append(f"  TOTAL: {estimate.get('total_engineer_days')}d")

    validation = state.get("validation") or {}
    lines += ["", "VALIDATION (coherence_validator)", f"  ok: {validation.get('ok')}"]
    for issue in validation.get("issues") or []:
        lines.append(f"  - {issue}")

    lines += ["", "HUMAN DECISION (human_review_gate)"]
    lines.append(f"  {state.get('human_decision')}")

    lines += ["", "AGENT CONTRIBUTIONS (audit trail — Level 3)"]
    for c in state.get("agent_contributions") or []:
        lines.append(
            f"  [{c.get('outcome')}] {c.get('agent')} -> {c.get('tool')}: {c.get('detail')}"
        )

    errors = state.get("errors") or []
    if errors:
        lines += ["", "ERRORS"]
        lines += [f"  - {e}" for e in errors]
    return "\n".join(lines)


async def _run(graph, transcript: str, thread_id: str, *, auto_resume: bool) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke({"transcript": transcript}, config)

    snapshot = await graph.aget_state(config)
    if snapshot.next and snapshot.interrupts:
        gate_value = snapshot.interrupts[0].value or {}
        print(f"\n  [PAUSED] human gate '{gate_value.get('gate')}' triggered")
        print(f"    reason: {gate_value.get('reason')}")
        if not auto_resume:
            print("    (--no-auto-resume: stopping here, checkpoint persisted)")
            return snapshot.values
        print(f"    auto-resume -> {_AUTO_DECISION}")
        await graph.ainvoke(Command(resume=_AUTO_DECISION), config)
        snapshot = await graph.aget_state(config)

    return snapshot.values


async def _main_async(args: argparse.Namespace) -> int:
    transcript_path = Path(args.transcript)
    if not transcript_path.is_file():
        print(f"ERROR: transcript not found: {transcript_path}", file=sys.stderr)
        return 1
    transcript = transcript_path.read_text(encoding="utf-8")
    thread_id = args.thread_id or f"s14-{transcript_path.stem}"

    print(f"transcript   : {transcript_path}")
    print(f"checkpointer : {'MemorySaver' if args.memory else 'AsyncPostgresSaver (pool)'}")
    print(f"thread_id    : {thread_id}\n")

    if args.memory:
        from langgraph.checkpoint.memory import MemorySaver

        graph = build_supervisor_graph(MemorySaver())
        state = await _run(graph, transcript, thread_id, auto_resume=not args.no_auto_resume)
    else:
        from app.domain.graph.checkpointer import open_checkpointer

        async with open_checkpointer() as checkpointer:
            graph = build_supervisor_graph(checkpointer)
            state = await _run(graph, transcript, thread_id, auto_resume=not args.no_auto_resume)

    rendered = _render(state)
    print("\n" + rendered)
    if args.out:
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
        print(f"\n(run written to {args.out})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Session 14 supervisor estimation graph.")
    parser.add_argument(
        "--transcript",
        default=str(DEFAULT_TRANSCRIPT),
        help="Path to a meeting transcript .txt (default: the S14 edge-case transcript).",
    )
    parser.add_argument(
        "--thread-id", help="Checkpointer thread_id (default derived from filename)."
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="Use an in-process MemorySaver instead of the Postgres checkpointer.",
    )
    parser.add_argument(
        "--no-auto-resume",
        action="store_true",
        help="Stop after the first pause instead of auto-resuming the human gate.",
    )
    parser.add_argument("--out", help="Write the rendered run to this file.")
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
