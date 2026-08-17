"""Unit tests for the three Session 6 stress metrics.

One passing case, one failing case, and one boundary case per metric — the
minimum the exercise asks for.
"""

from __future__ import annotations

import pytest

from app.schemas.estimation import TurnObservation
from evals.stress.metrics import CostBudgetMetric, LatencyBudgetMetric, MemoryDriftMetric


def _observation(**overrides) -> TurnObservation:
    defaults = dict(
        turn_index=1,
        session_id="s1",
        enriched_transcript_chars=100,
        attachments_total_chars=0,
        messages_in_window=2,
        anchors_count=0,
        summary_chars=0,
        tokens_in=500,
        tokens_out=200,
        cost_usd=0.001,
        latency_ms=1000,
        cache_hit_kind="none",
        last_resolved_tier=None,
    )
    defaults.update(overrides)
    return TurnObservation(**defaults)


class TestLatencyBudgetMetric:
    def test_passes_when_under_budget(self):
        metric = LatencyBudgetMetric(budget_ms=8000)
        result = metric.evaluate(_observation(latency_ms=3000))
        assert result.passed is True
        assert result.score == 1.0

    def test_fails_when_over_budget(self):
        metric = LatencyBudgetMetric(budget_ms=8000)
        result = metric.evaluate(_observation(latency_ms=12000))
        assert result.passed is False
        assert result.score == 0.0

    def test_boundary_exact_budget_passes(self):
        metric = LatencyBudgetMetric(budget_ms=8000)
        result = metric.evaluate(_observation(latency_ms=8000))
        assert result.passed is True

    def test_rejects_non_positive_budget(self):
        with pytest.raises(ValueError):
            LatencyBudgetMetric(budget_ms=0)


class TestCostBudgetMetric:
    def test_passes_when_under_budget(self):
        metric = CostBudgetMetric(budget_usd=0.02)
        result = metric.evaluate(_observation(cost_usd=0.005))
        assert result.passed is True

    def test_fails_when_over_budget(self):
        metric = CostBudgetMetric(budget_usd=0.02)
        result = metric.evaluate(_observation(cost_usd=0.05))
        assert result.passed is False

    def test_boundary_exact_budget_passes(self):
        metric = CostBudgetMetric(budget_usd=0.02)
        result = metric.evaluate(_observation(cost_usd=0.02))
        assert result.passed is True

    def test_rejects_non_positive_budget(self):
        with pytest.raises(ValueError):
            CostBudgetMetric(budget_usd=0.0)


class TestMemoryDriftMetric:
    def test_passes_when_fact_present(self):
        metric = MemoryDriftMetric(fact="Nimbus", fact_field="project_name")
        snapshot = {"metadata": {"project_name": "Project Nimbus"}}
        result = metric.evaluate(snapshot)
        assert result.passed is True

    def test_fails_when_fact_missing(self):
        metric = MemoryDriftMetric(fact="Nimbus", fact_field="project_name")
        snapshot = {"metadata": {"project_name": "Something Else"}}
        result = metric.evaluate(snapshot)
        assert result.passed is False

    def test_any_field_searches_whole_snapshot(self):
        metric = MemoryDriftMetric(fact="30000 EUR", fact_field="any")
        snapshot = {"metadata": {"agreed_scope": None}, "summary": "Budget agreed: 30000 EUR"}
        result = metric.evaluate(snapshot)
        assert result.passed is True

    def test_case_insensitive_match(self):
        metric = MemoryDriftMetric(fact="flutter", fact_field="technologies")
        snapshot = {"metadata": {"mentioned_technologies": ["Flutter", "PostgreSQL"]}}
        result = metric.evaluate(snapshot)
        assert result.passed is True

    def test_rejects_empty_fact(self):
        with pytest.raises(ValueError):
            MemoryDriftMetric(fact="")
