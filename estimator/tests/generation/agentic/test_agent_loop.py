"""Flow tests for the manual Responses API agent loop (Session 12).

The Responses API client is faked entirely: these tests validate the loop's
wiring (call_id correctness, termination, the max_iterations safeguard), not
the OpenAI SDK or any real model behaviour.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.generation.agentic.agent_loop import run_agent
from app.generation.agentic.agent_schemas import AgentEstimate


def _function_call(call_id: str, name: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(
        type="function_call", call_id=call_id, name=name, arguments=json.dumps(arguments)
    )


def _reasoning(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="reasoning", summary=[SimpleNamespace(text=text)])


def _response(response_id: str, output: list) -> SimpleNamespace:
    return SimpleNamespace(id=response_id, output=output)


_FINAL_ESTIMATE = AgentEstimate(
    components=[
        {
            "name": "Auth backend",
            "estimated_hours": 483.0,
            "reference_count": 1,
            "unbudgeted": False,
        },
        {"name": "Mobile app", "estimated_hours": 897.0, "reference_count": 1, "unbudgeted": False},
    ],
    total_hours=1380.0,
    confidence="high",
    assumptions=["Greenfield build."],
    summary="Two-component estimate.",
)


class _FakeResponses:
    """Stand-in for ``client.responses`` — pops scripted turns, records calls."""

    def __init__(self, turns: list, final_estimate: AgentEstimate = _FINAL_ESTIMATE):
        self._turns = list(turns)
        self._final_estimate = final_estimate
        self.create_calls: list[dict] = []
        self.parse_calls: list[dict] = []

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return self._turns.pop(0)

    async def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        return SimpleNamespace(output_parsed=self._final_estimate)


class _FakeClient:
    def __init__(self, turns: list, final_estimate: AgentEstimate = _FINAL_ESTIMATE):
        self.responses = _FakeResponses(turns, final_estimate)


async def _stub_backend(query: str, filters: dict | None) -> list[dict]:
    return [
        {
            "id": 1,
            "content_preview": query,
            "sector": "finance",
            "budget_id": "B1",
            "estimated_hours": 420.0,
            "distance": 0.1,
        }
    ]


async def test_run_agent_completes_naturally_with_parallel_searches_then_calculate():
    turn1 = _response(
        "r1",
        [
            _reasoning("Two components: auth backend and mobile app."),
            _function_call("call_1", "search_budgets", {"query": "Auth backend", "filters": None}),
            _function_call("call_2", "search_budgets", {"query": "Mobile app", "filters": None}),
        ],
    )
    turn2 = _response(
        "r2",
        [
            _reasoning("Both searched, now calculate."),
            _function_call(
                "call_3",
                "calculate_estimate",
                {
                    "components": [
                        {"name": "Auth backend", "reference_amounts": [420.0]},
                        {"name": "Mobile app", "reference_amounts": [780.0]},
                    ]
                },
            ),
        ],
    )
    turn3 = _response("r3", [])  # no more function_call items -> natural termination

    client = _FakeClient([turn1, turn2, turn3])

    result = await run_agent(
        "some transcript",
        client=client,
        model="gpt-5-mini",
        reasoning_effort="minimal",
        max_iterations=8,
        retrieval_backend=_stub_backend,
    )

    assert result.stopped_reason == "completed"
    assert result.iterations == 3
    assert len(result.trace) == 3
    assert result.trace[0].action == "search_budgets(query='Auth backend', filters=None)"
    assert result.trace[1].reasoning == "(parallel tool call in the same turn as the previous step)"
    assert result.trace[2].action.startswith("calculate_estimate(")
    assert result.estimate is _FINAL_ESTIMATE

    # call_id correctness: the second create() call must reference call_1/call_2, in order.
    second_call_input = client.responses.create_calls[1]["input"]
    assert [item["call_id"] for item in second_call_input] == ["call_1", "call_2"]
    # previous_response_id chains to the prior turn's response id.
    assert client.responses.create_calls[1]["previous_response_id"] == "r1"
    assert client.responses.create_calls[2]["previous_response_id"] == "r2"
    # The final structured call chains off the last turn too.
    assert client.responses.parse_calls[0]["previous_response_id"] == "r3"


async def test_run_agent_reports_dangling_tool_error_as_an_observation_not_a_crash():
    turn1 = _response(
        "r1", [_function_call("call_1", "search_budgets", {"query": "x", "filters": None})]
    )
    turn2 = _response("r2", [])
    client = _FakeClient([turn1, turn2])

    async def failing_backend(query, filters):
        raise RuntimeError("pgvector unreachable")

    result = await run_agent(
        "t",
        client=client,
        model="m",
        reasoning_effort="minimal",
        max_iterations=8,
        retrieval_backend=failing_backend,
    )

    assert result.stopped_reason == "completed"
    assert "error: pgvector unreachable" in result.trace[0].observation


async def test_run_agent_stops_at_max_iterations_even_if_model_keeps_calling_tools():
    def _infinite_turns():
        i = 0
        while True:
            i += 1
            yield _response(
                f"r{i}",
                [
                    _function_call(
                        f"call_{i}", "search_budgets", {"query": f"q{i}", "filters": None}
                    )
                ],
            )

    turns = _infinite_turns()

    class _InfiniteResponses:
        def __init__(self):
            self.create_calls: list[dict] = []

        async def create(self, **kwargs):
            self.create_calls.append(kwargs)
            return next(turns)

        async def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=_FINAL_ESTIMATE)

    class _InfiniteClient:
        def __init__(self):
            self.responses = _InfiniteResponses()

    client = _InfiniteClient()

    result = await run_agent(
        "t",
        client=client,
        model="m",
        reasoning_effort="minimal",
        max_iterations=3,
        retrieval_backend=_stub_backend,
    )

    assert result.stopped_reason == "max_iterations"
    assert result.iterations == 3
    assert len(result.trace) == 3
