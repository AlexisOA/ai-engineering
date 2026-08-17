"""Three deterministic metrics for the Session 6 stress exercise.

These sit next to ``evals.metrics`` rather than inside it because they
evaluate a different shape: a single ``TurnObservation`` (the stress
runner's telemetry) or a session snapshot dict (the JSON body of
``GET /sessions/{id}``), not an ``(GoldenCase, EstimationResult)`` pair. The
``MetricResult`` dataclass is imported and reused as-is so every report the
project produces — golden-set or stress-test — reads the same way.

No embeddings, no LLM-as-judge: a budget is either respected or it is not,
and a fact is either still present in the snapshot or it has been dropped.
Keeping the check to a case-insensitive substring match means a red result
always means the same thing — the fact is gone — instead of "the judge
model felt less confident this time".
"""

from __future__ import annotations

import json
from typing import Any, Literal

from app.schemas.estimation import TurnObservation
from evals.metrics import MetricResult

FactField = Literal["project_name", "technologies", "scope", "summary", "any"]


class LatencyBudgetMetric:
    """Turns a latency SLA into a pass/fail check on one turn's telemetry."""

    name = "latency_budget"

    def __init__(self, budget_ms: int) -> None:
        if budget_ms <= 0:
            raise ValueError("budget_ms must be a positive number of milliseconds")
        self.budget_ms = budget_ms

    def evaluate(self, observation: TurnObservation) -> MetricResult:
        passed = observation.latency_ms <= self.budget_ms
        return MetricResult(
            name=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            details=f"latency_ms={observation.latency_ms} budget_ms={self.budget_ms}",
        )


class CostBudgetMetric:
    """Turns a per-turn cost SLA into a pass/fail check.

    Deliberately per-turn, not cumulative: the runner is free to compute the
    running total across a scenario separately (it needs that number for
    the cost-vs-turn curve anyway), but a budget that grows with the
    conversation would stop meaning "this turn is affordable".
    """

    name = "cost_budget"

    def __init__(self, budget_usd: float) -> None:
        if budget_usd <= 0:
            raise ValueError("budget_usd must be a positive dollar amount")
        self.budget_usd = budget_usd

    def evaluate(self, observation: TurnObservation) -> MetricResult:
        passed = observation.cost_usd <= self.budget_usd
        return MetricResult(
            name=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            details=f"cost_usd={observation.cost_usd:.6f} budget_usd={self.budget_usd:.6f}",
        )


_FIELD_GETTERS = {
    "project_name": lambda snapshot: str((snapshot.get("metadata") or {}).get("project_name") or ""),
    "technologies": lambda snapshot: " ".join(
        (snapshot.get("metadata") or {}).get("mentioned_technologies") or []
    ),
    "scope": lambda snapshot: str((snapshot.get("metadata") or {}).get("agreed_scope") or ""),
    "summary": lambda snapshot: str(snapshot.get("summary") or ""),
}


class MemoryDriftMetric:
    """Has a fact introduced earlier in the conversation survived to now?

    ``fact_field`` narrows the search to one slice of the session snapshot
    (``"project_name"``, ``"technologies"``, ``"scope"``, ``"summary"``) or
    falls back to ``"any"``, which serialises the whole snapshot (metadata,
    anchors, summary, tier) and searches all of it — useful when a fact
    could plausibly have moved between fields (e.g. promoted into an
    anchor). Matching is a case-insensitive substring; good enough to answer
    "is the turn-N fact still visible anywhere obvious" without wading into
    fuzzy-match edge cases the exercise explicitly rules out.
    """

    name = "memory_drift"

    def __init__(self, fact: str, fact_field: FactField = "any") -> None:
        if not fact:
            raise ValueError("fact must be a non-empty string to search for")
        self.fact = fact
        self.fact_field = fact_field

    def evaluate(self, snapshot: dict[str, Any]) -> MetricResult:
        haystack = self._haystack(snapshot)
        found = self.fact.lower() in haystack.lower()
        return MetricResult(
            name=self.name,
            score=1.0 if found else 0.0,
            passed=found,
            details=f"fact={self.fact!r} field={self.fact_field} found={found}",
        )

    def _haystack(self, snapshot: dict[str, Any]) -> str:
        if self.fact_field == "any":
            return json.dumps(snapshot, default=str)
        getter = _FIELD_GETTERS[self.fact_field]
        return getter(snapshot)
