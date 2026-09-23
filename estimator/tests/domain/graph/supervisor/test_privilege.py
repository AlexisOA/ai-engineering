"""``call_tool`` enforces minimum privilege and audits every call (Level 3)."""

from __future__ import annotations

import pytest

from app.domain.graph.supervisor.privilege import PrivilegeViolation, call_tool


@pytest.mark.asyncio
async def test_allowed_call_runs_and_returns_ok_contribution():
    async def fake_tool(x):
        return {"doubled": x * 2}

    result, contribution = await call_tool("budget_searcher", "search_budgets", fake_tool, 21)

    assert result == {"doubled": 42}
    assert contribution == {
        "agent": "budget_searcher",
        "tool": "search_budgets",
        "outcome": "ok",
        "detail": "search_budgets ok",
    }


@pytest.mark.asyncio
async def test_denied_call_never_executes_the_tool():
    calls = []

    async def fake_tool(x):
        calls.append(x)
        return x

    with pytest.raises(PrivilegeViolation) as exc_info:
        # budget_searcher is only privileged for search_budgets, not validate_estimate.
        await call_tool("budget_searcher", "validate_estimate", fake_tool, 1)

    assert calls == []  # the tool never ran
    contribution = exc_info.value.contribution
    assert contribution["outcome"] == "denied"
    assert contribution["agent"] == "budget_searcher"
    assert contribution["tool"] == "validate_estimate"


@pytest.mark.asyncio
async def test_requirements_extractor_has_no_tool_privilege():
    async def fake_tool():
        return {}

    with pytest.raises(PrivilegeViolation):
        await call_tool("requirements_extractor", "search_budgets", fake_tool)


@pytest.mark.asyncio
async def test_tool_failure_is_logged_as_error_and_reraised():
    def broken_tool():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await call_tool("coherence_validator", "validate_estimate", broken_tool)
