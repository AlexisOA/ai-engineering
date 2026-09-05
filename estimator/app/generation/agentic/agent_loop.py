"""The hand-rolled agent loop (Session 12) — driven manually over the Responses API.

DELIBERATE EXCEPTION to the "everything goes through LLMWrapper" rule: this is
the one place in the service that calls the raw OpenAI Responses API
(``client.responses.create``/``responses.parse``) directly, because that API's
own function-calling mechanics (``function_call``/``call_id``/
``previous_response_id`` chaining) are the entire point of the exercise — an
Instructor/LiteLLM abstraction would hide exactly what this module exists to
show. Do not "fix" this to go through ``LLMWrapper``.

The loop: call the model, walk its output for ``function_call`` items, execute
each via :func:`app.generation.agentic.agent_tools.dispatch_tool`, feed the
results back as ``function_call_output`` items chained on
``previous_response_id``, repeat until the model stops calling tools (or
``max_iterations`` is hit as a hard safeguard), then ask for the final
structured estimate via ``responses.parse``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.generation.agentic.agent_schemas import AgentEstimate, AgentRunResult, AgentTraceStep
from app.generation.agentic.agent_tools import TOOL_SCHEMAS, RetrievalBackend, dispatch_tool

if TYPE_CHECKING:
    from openai import AsyncOpenAI

SYSTEM_PROMPT = (
    "You are a senior software-delivery estimator working from a raw client meeting "
    "transcript. Follow this method:\n"
    "1. Decompose the transcript into the distinct functional COMPONENTS the client "
    "described. A component is a piece of work with its own scope and technology — "
    "do not split one component into several, and do not merge unrelated components "
    "into one.\n"
    "2. For EVERY component, call search_budgets with a specific, technical query "
    "describing just that component, to find comparable historical engineer-hours. "
    "If a search returns nothing, retry with a broader or differently-worded query "
    "before moving on to the next component.\n"
    "3. Once every component has been searched (even ones with no match), call "
    "calculate_estimate exactly once with all of them and their reference_amounts.\n"
    "4. Call validate_estimate as your last tool call, on the exact result "
    "calculate_estimate returned, before giving your final answer.\n"
    "5. Never invent an hours figure yourself — every number in your final answer "
    "must trace back to calculate_estimate's output.\n"
    "You have three tools: search_budgets, calculate_estimate, validate_estimate."
)

_FINAL_ANSWER_PROMPT = (
    "Produce the final structured estimate now, consolidating every component you "
    "searched and costed above. Do not invent numbers outside what calculate_estimate "
    "returned."
)


def _extract_reasoning(response: Any) -> str:
    """Concatenate the reasoning-summary text items in one Responses API turn."""
    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "reasoning":
            continue
        for part in getattr(item, "summary", []) or []:
            text = getattr(part, "text", None)
            if text:
                parts.append(text)
    return "\n".join(parts) if parts else "(no reasoning summary returned)"


def _render_action(name: str, arguments: dict[str, Any]) -> str:
    """Render a tool call as a readable signature for the trace."""
    args_repr = ", ".join(f"{key}={value!r}" for key, value in arguments.items())
    return f"{name}({args_repr})"


def _summarize_observation(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> str:
    """Render a tool result as a short trace observation."""
    if "error" in result:
        return f"error: {result['error']}"
    if name == "search_budgets":
        count = result["count"]
        query = arguments.get("query", "")
        if count == 0:
            return f"no historical items for '{query}'"
        hours = [item.get("estimated_hours") for item in result["items"]]
        return f"{count} historical items for '{query}'; hours={hours}"
    return result.get("summary", str(result))


def render_trace(steps: list[AgentTraceStep]) -> str:
    """Render the trace in the format the exercise asks for: one block per step."""
    lines: list[str] = []
    for item in steps:
        lines.append(f"STEP {item.step}")
        lines.append(f"  reasoning:   {item.reasoning}")
        lines.append(f"  action:      {item.action}")
        lines.append(f"  observation: {item.observation}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


async def run_agent(
    transcript: str,
    *,
    client: "AsyncOpenAI",
    model: str,
    reasoning_effort: str,
    max_iterations: int,
    retrieval_backend: RetrievalBackend,
) -> AgentRunResult:
    """Run the manual reason -> act -> observe loop to completion.

    Parameters
    ----------
    transcript:
        Raw client meeting transcript.
    client:
        An ``AsyncOpenAI`` client (or any object exposing the same
        ``responses.create``/``responses.parse`` async interface — a fake is
        injected in tests).
    model, reasoning_effort:
        Passed straight through to every ``responses.create``/``parse`` call.
    max_iterations:
        Hard cap on the number of tool calls executed, independent of whether
        the model would keep calling tools — the safeguard the exercise asks for
        in addition to the loop's natural termination.
    retrieval_backend:
        Injected historical-budget search (real pipeline or offline stub) — see
        :data:`app.generation.agentic.agent_tools.RetrievalBackend`.
    """
    trace: list[AgentTraceStep] = []
    step = 0
    stopped_reason: str = "completed"

    response = await client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        tools=TOOL_SCHEMAS,
        reasoning={"effort": reasoning_effort, "summary": "auto"},
        store=True,
    )

    while True:
        function_calls = [
            item for item in response.output if getattr(item, "type", None) == "function_call"
        ]
        if not function_calls:
            break

        reasoning_text = _extract_reasoning(response)
        outputs: list[dict[str, Any]] = []
        hit_limit = False

        for index, call in enumerate(function_calls):
            if step >= max_iterations:
                hit_limit = True
                break
            step += 1
            arguments = json.loads(call.arguments)
            action = _render_action(call.name, arguments)
            reasoning_for_step = (
                reasoning_text
                if index == 0
                else "(parallel tool call in the same turn as the previous step)"
            )
            try:
                result = await dispatch_tool(call.name, arguments, backend=retrieval_backend)
            except Exception as exc:  # noqa: BLE001 — surfaced as an observation, not a crash
                result = {"error": str(exc)}
            observation = _summarize_observation(call.name, arguments, result)

            trace.append(
                AgentTraceStep(
                    step=step, reasoning=reasoning_for_step, action=action, observation=observation
                )
            )
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result),
                }
            )

        if hit_limit:
            stopped_reason = "max_iterations"
            break

        response = await client.responses.create(
            model=model,
            previous_response_id=response.id,
            input=outputs,
            tools=TOOL_SCHEMAS,
            reasoning={"effort": reasoning_effort, "summary": "auto"},
            store=True,
        )

    final = await client.responses.parse(
        model=model,
        previous_response_id=response.id,
        input=[{"role": "user", "content": _FINAL_ANSWER_PROMPT}],
        text_format=AgentEstimate,
        reasoning={"effort": reasoning_effort},
    )

    return AgentRunResult(
        estimate=final.output_parsed,
        trace=trace,
        iterations=step,
        stopped_reason=stopped_reason,
    )
