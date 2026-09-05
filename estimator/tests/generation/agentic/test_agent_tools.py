"""Unit tests for the agent's tools (Session 12)."""

from __future__ import annotations

import pytest

from app.generation.agentic.agent_tools import (
    calculate_estimate,
    dispatch_tool,
    search_budgets,
    validate_estimate,
)


def test_calculate_estimate_uses_median_and_contingency():
    result = calculate_estimate(
        {"components": [{"name": "Auth", "reference_amounts": [400, 380, 420]}]}
    )
    component = result["components"][0]
    # median(400, 380, 420) = 400; +15% contingency = 460.0
    assert component["estimated_hours"] == 460.0
    assert component["reference_count"] == 3
    assert component["unbudgeted"] is False
    assert result["total_hours"] == 460.0


def test_calculate_estimate_flags_empty_references_as_unbudgeted():
    result = calculate_estimate({"components": [{"name": "Ghost", "reference_amounts": []}]})
    component = result["components"][0]
    assert component["unbudgeted"] is True
    assert component["estimated_hours"] == 0.0
    assert result["total_hours"] == 0.0


def test_calculate_estimate_totals_across_components():
    result = calculate_estimate(
        {
            "components": [
                {"name": "A", "reference_amounts": [100]},
                {"name": "B", "reference_amounts": [200]},
            ]
        }
    )
    # median(100)=100 -> 115.0 ; median(200)=200 -> 230.0
    assert result["total_hours"] == pytest.approx(345.0)
    assert result["summary"] == "total=345.0h across 2 components"


def test_validate_estimate_passes_a_coherent_estimate():
    report = validate_estimate(
        {
            "components": [
                {"name": "Auth", "estimated_hours": 460.0, "reference_amounts": [400, 420]}
            ],
            "total_hours": 460.0,
        }
    )
    assert report["passed"] is True
    assert report["issues"] == []


def test_validate_estimate_flags_incoherent_total():
    report = validate_estimate(
        {
            "components": [
                {"name": "Auth", "estimated_hours": 460.0, "reference_amounts": [400, 420]}
            ],
            "total_hours": 999.0,
        }
    )
    assert report["passed"] is False
    assert any("does not match" in issue for issue in report["issues"])


def test_validate_estimate_flags_unbudgeted_component():
    report = validate_estimate(
        {
            "components": [{"name": "Ghost", "estimated_hours": 0.0, "reference_amounts": []}],
            "total_hours": 0.0,
        }
    )
    assert report["passed"] is False
    assert any("no historical reference" in issue for issue in report["issues"])


def test_validate_estimate_flags_out_of_range_hours():
    report = validate_estimate(
        {
            "components": [
                {"name": "Auth", "estimated_hours": 5000.0, "reference_amounts": [400, 420]}
            ],
            "total_hours": 5000.0,
        }
    )
    assert report["passed"] is False
    assert any("far outside" in issue for issue in report["issues"])


async def test_search_budgets_wraps_the_injected_backend():
    async def backend(query, filters):
        assert query == "OAuth backend"
        assert filters == {"sectors": ["finance"]}
        return [{"id": 1, "estimated_hours": 420.0}]

    result = await search_budgets(
        {"query": "OAuth backend", "filters": {"sectors": ["finance"]}}, backend=backend
    )
    assert result == {"items": [{"id": 1, "estimated_hours": 420.0}], "count": 1}


async def test_search_budgets_empty_result_is_not_an_error():
    async def backend(query, filters):
        return []

    result = await search_budgets({"query": "nothing matches this"}, backend=backend)
    assert result == {"items": [], "count": 0}


async def test_dispatch_tool_routes_by_name():
    async def backend(query, filters):
        return [{"id": 1, "estimated_hours": 100.0}]

    searched = await dispatch_tool("search_budgets", {"query": "x"}, backend=backend)
    assert searched["count"] == 1

    calculated = await dispatch_tool(
        "calculate_estimate",
        {"components": [{"name": "A", "reference_amounts": [100]}]},
        backend=backend,
    )
    assert calculated["total_hours"] == 115.0

    validated = await dispatch_tool(
        "validate_estimate",
        {
            "components": [{"name": "A", "estimated_hours": 115.0, "reference_amounts": [100]}],
            "total_hours": 115.0,
        },
        backend=backend,
    )
    assert validated["passed"] is True


async def test_dispatch_tool_rejects_unknown_name():
    async def backend(query, filters):
        return []

    with pytest.raises(ValueError, match="Unknown tool"):
        await dispatch_tool("delete_everything", {}, backend=backend)
