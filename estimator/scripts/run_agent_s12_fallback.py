#!/usr/bin/env python3
"""Session 12 agent — LOCAL-STUB + CLAUDE FALLBACK, for a real trace without OpenAI credit.

DEVIATION FROM THE REAL PIPELINE, documented (not hidden) — same situation and
same posture as ``scripts/eval_ragas_s11_fallback.py`` in Session 11: the org's
OpenAI credit balance is exhausted, and this exercise's real implementation
(``app/generation/agentic/agent_loop.py``) deliberately calls the raw OpenAI
Responses API, which needs that same credit. Two substitutions, both disclosed:

* LLM: OpenAI Responses API (``client.responses.create``) -> Anthropic Messages
  API (``client.messages.create``), via a small local driver in this script.
  The mechanics differ (Anthropic's ``tool_use``/``tool_result`` content blocks,
  growing message list, no ``previous_response_id`` — vs. ``function_call``
  items and stateful chaining) but the LOOP SHAPE is the same: reason -> act
  -> observe -> repeat, with a hard max-iterations safeguard.
* Retrieval: the real hybrid+rerank pipeline also needs OpenAI (embeddings), so
  this run uses ``exercises/session-12/reference_retrieval.py``'s
  ``search_budgets_stub`` — the exercise's OWN safety-net stub for exactly this
  situation ("úsalo solo si tu pipeline no está listo"), not something invented
  for this fallback.

The tools themselves (``app.generation.agentic.agent_tools`` — schemas,
``calculate_estimate``, ``validate_estimate``) and the trace/estimate schemas
(``app.generation.agentic.agent_schemas``) are the REAL, unmodified Session 12
code; only the LLM-calling shell and the retrieval backend differ.

Once OpenAI credit is restored, ``scripts/run_agent_s12.py`` (Responses API +
real retrieval) is the canonical path; this file stays a documented one-off.

Usage::

    uv run python scripts/run_agent_s12_fallback.py \\
        exercises/session-12/sample_transcript_complex.txt \\
        --out exercises/session-12/trace_complex_claude_fallback.txt
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anthropic import AsyncAnthropic  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.generation.agentic.agent_loop import (  # noqa: E402
    SYSTEM_PROMPT,
    _render_action,
    _summarize_observation,
    render_trace,
)
from app.generation.agentic.agent_schemas import AgentEstimate, AgentRunResult, AgentTraceStep  # noqa: E402
from app.generation.agentic.agent_tools import TOOL_SCHEMAS, dispatch_tool  # noqa: E402

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 4000

_FINAL_JSON_PROMPT = (
    "Produce the final structured estimate now, consolidating every component you "
    "searched and costed above. Reply with ONLY a single JSON object matching this "
    "JSON Schema exactly — no markdown fences, no commentary before or after:\n\n"
    "{schema}"
)


def _to_anthropic_tools(tool_schemas: list[dict]) -> list[dict]:
    """Responses API's flat tool shape -> Anthropic's {name, description, input_schema}."""
    return [
        {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
        for t in tool_schemas
    ]


def _parse_estimate_json(text: str) -> AgentEstimate:
    """Extract a JSON object from the model's final text reply and validate it."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in the final reply: {text!r}")
    return AgentEstimate.model_validate(json.loads(match.group(0)))


async def run_agent_claude_fallback(
    transcript: str,
    *,
    client: AsyncAnthropic,
    retrieval_backend,
    max_iterations: int,
) -> AgentRunResult:
    """Same reason->act->observe loop as run_agent(), driven over Claude's tool-use API."""
    tools = _to_anthropic_tools(TOOL_SCHEMAS)
    messages: list[dict] = [{"role": "user", "content": transcript}]
    trace: list[AgentTraceStep] = []
    step = 0
    stopped_reason = "completed"

    response = await client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT, tools=tools, messages=messages
    )

    while True:
        tool_uses = [block for block in response.content if block.type == "tool_use"]
        if not tool_uses:
            break

        reasoning_text = (
            "\n".join(block.text for block in response.content if block.type == "text")
            or "(no reasoning text returned)"
        )
        messages.append({"role": "assistant", "content": response.content})

        tool_results: list[dict] = []
        hit_limit = False
        for index, block in enumerate(tool_uses):
            if step >= max_iterations:
                hit_limit = True
                break
            step += 1
            arguments = block.input
            action = _render_action(block.name, arguments)
            reasoning_for_step = (
                reasoning_text
                if index == 0
                else "(parallel tool call in the same turn as the previous step)"
            )
            try:
                result = await dispatch_tool(block.name, arguments, backend=retrieval_backend)
            except Exception as exc:  # noqa: BLE001
                result = {"error": str(exc)}
            observation = _summarize_observation(block.name, arguments, result)

            trace.append(
                AgentTraceStep(
                    step=step, reasoning=reasoning_for_step, action=action, observation=observation
                )
            )
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)}
            )

        if hit_limit:
            stopped_reason = "max_iterations"
            break

        messages.append({"role": "user", "content": tool_results})
        response = await client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT, tools=tools, messages=messages
        )

    messages.append({"role": "assistant", "content": response.content})
    schema = json.dumps(AgentEstimate.model_json_schema())
    messages.append({"role": "user", "content": _FINAL_JSON_PROMPT.format(schema=schema)})
    final_response = await client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT, messages=messages
    )
    text = "".join(block.text for block in final_response.content if block.type == "text")
    estimate = _parse_estimate_json(text)

    return AgentRunResult(
        estimate=estimate, trace=trace, iterations=step, stopped_reason=stopped_reason
    )


def _stub_backend():
    exercises_dir = ROOT / "exercises" / "session-12"
    if str(exercises_dir) not in sys.path:
        sys.path.insert(0, str(exercises_dir))
    from reference_retrieval import search_budgets_stub

    async def backend(query: str, filters: dict | None) -> list[dict]:
        return search_budgets_stub(query, filters)

    return backend


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--max-iterations", type=int, default=8)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY is not configured.", file=sys.stderr)
        return 1

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    transcript = args.transcript.read_text(encoding="utf-8")

    result = await run_agent_claude_fallback(
        transcript,
        client=client,
        retrieval_backend=_stub_backend(),
        max_iterations=args.max_iterations,
    )

    trace_text = render_trace(result.trace)
    report = (
        "# DEVIATION (disclosed): Claude (not gpt-5 Responses API) + the offline "
        "reference_retrieval.py stub (not the real pipeline) — OpenAI credit was "
        "exhausted the day this ran. See scripts/run_agent_s12_fallback.py docstring.\n\n"
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
