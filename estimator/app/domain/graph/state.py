"""Typed state for the Session 13 estimation graph.

``budget_matches`` and ``errors`` are accumulator fields: each node returns only
its own partial update (e.g. the matches found for the one component it just
searched), and LangGraph's ``operator.add`` reducer appends it onto whatever the
previous nodes already contributed, rather than the node having to read and
rewrite the whole running list itself.
"""

from __future__ import annotations

import operator
from typing import Annotated, Optional, TypedDict


class Component(TypedDict):
    """A functional component the transcript was decomposed into."""

    name: str
    category: str


class BudgetMatch(TypedDict):
    """One historical reference found for a component."""

    component: str
    reference_budget_id: str
    amount: float


class EstimationState(TypedDict, total=False):
    transcript: str
    requirements: list[str]
    components: list[Component]
    # Accumulator: grows by one component's matches per search_budgets call.
    budget_matches: Annotated[list[BudgetMatch], operator.add]
    estimate: Optional[dict]
    status: Optional[str]  # "validated" | "needs_review"
    # Accumulator: any node can append a component-scoped failure without
    # aborting the rest of the graph.
    errors: Annotated[list[str], operator.add]
