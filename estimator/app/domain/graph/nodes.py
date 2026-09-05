"""The five sequential nodes (Session 13). Each is a pure function: state in,
partial update out — LangGraph's reducers (``state.py``) merge the update into
the running state, so a node never has to read-modify-write the whole thing.

``search_budgets`` is the one node whose real dependency (historical-budget
retrieval) is injected rather than imported, via :func:`make_search_budgets_node`
— consistent with how the rest of the ``agentic``/``rag`` split already keeps
retrieval swappable (see ``app/generation/rag/agent_retrieval.py``).
"""

from __future__ import annotations

import asyncio
import statistics
from typing import Any

import logfire
import structlog

from app.config import get_settings
from app.dependencies import get_llm_wrapper
from app.domain.graph.schemas import ComponentsList, RequirementsList
from app.domain.graph.state import BudgetMatch, EstimationState
from app.generation.rag.agent_retrieval import RetrievalBackend

log = structlog.get_logger()

# Same buffer as the Session 12 calculate_estimate — transparent, no hidden layers.
CONTINGENCY_FACTOR = 0.15
_TOTAL_TOLERANCE_HOURS = 0.5

_EXTRACT_SYSTEM_PROMPT = (
    "You are a software-delivery analyst. Read the client meeting transcript and "
    "extract a flat list of atomic requirements — one short, concrete, technical "
    "sentence each. Ignore small talk and digressions. Do not group or "
    "categorize yet, just enumerate what the client asked for, in the order "
    "it came up."
)

_CLASSIFY_SYSTEM_PROMPT = (
    "Group the requirements below into functional COMPONENTS — the distinct "
    "pieces of work the client would recognise as separate deliverables (e.g. "
    "'a backend', 'an ERP integration', 'a mobile app'), not implementation "
    "details of one deliverable. A specific technology choice (a database, a "
    "cache, a queue) mentioned as part of building ONE component is a detail of "
    "that component, not a component of its own — do not split a single system "
    "into one component per technology. Each component has a short name and a "
    "category (e.g. 'backend', 'integration', 'mobile', 'analytics', "
    "'infrastructure')."
)


def _model_kwargs(model: str, reasoning_effort: str) -> dict[str, Any]:
    """``reasoning_effort`` only applies to the gpt-5 family. Passing it with a
    Claude model breaks Instructor's structured extraction (litellm maps it to
    "thinking", which Anthropic rejects together with a forced tool_choice)."""
    if model.startswith("gpt-5"):
        return {"reasoning_effort": reasoning_effort}
    return {}


async def extract_requirements(state: EstimationState) -> dict:
    with logfire.span("node: extract_requirements"):
        settings = get_settings()
        wrapper = get_llm_wrapper()
        try:
            result, _meta = await asyncio.to_thread(
                wrapper.complete_structured,
                system_prompt=_EXTRACT_SYSTEM_PROMPT,
                user_message=state["transcript"],
                response_model=RequirementsList,
                model_override=settings.AGENT_MODEL,
                max_tokens=2000,
                **_model_kwargs(settings.AGENT_MODEL, settings.AGENT_REASONING_EFFORT),
            )
        except Exception as exc:  # noqa: BLE001
            log.error("extract_requirements_failed", error=str(exc)[:300])
            return {"requirements": [], "errors": [f"extract_requirements: {exc}"]}
        return {"requirements": result.requirements}


async def classify_components(state: EstimationState) -> dict:
    with logfire.span("node: classify_components"):
        requirements = state.get("requirements", [])
        if not requirements:
            return {
                "components": [],
                "errors": ["classify_components: no requirements to classify"],
            }

        settings = get_settings()
        wrapper = get_llm_wrapper()
        user_message = "\n".join(f"- {r}" for r in requirements)
        try:
            result, _meta = await asyncio.to_thread(
                wrapper.complete_structured,
                system_prompt=_CLASSIFY_SYSTEM_PROMPT,
                user_message=user_message,
                response_model=ComponentsList,
                model_override=settings.AGENT_MODEL,
                max_tokens=2000,
                **_model_kwargs(settings.AGENT_MODEL, settings.AGENT_REASONING_EFFORT),
            )
        except Exception as exc:  # noqa: BLE001
            log.error("classify_components_failed", error=str(exc)[:300])
            return {"components": [], "errors": [f"classify_components: {exc}"]}
        components = [{"name": c.name, "category": c.category} for c in result.components]
        return {"components": components}


def make_search_budgets_node(backend: RetrievalBackend):
    """Build the ``search_budgets`` node bound to one retrieval backend.

    Sequential by design (Level 1): one component after another. Parallelising
    this per-component search (the Send API) is live-session work.
    """

    async def search_budgets(state: EstimationState) -> dict:
        with logfire.span("node: search_budgets"):
            matches: list[BudgetMatch] = []
            errors: list[str] = []
            for component in state.get("components", []):
                try:
                    items = await backend(component["name"], None)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"search_budgets({component['name']}): {exc}")
                    continue
                for item in items:
                    matches.append(
                        {
                            "component": component["name"],
                            "reference_budget_id": str(item.get("budget_id") or item.get("id")),
                            "amount": float(item.get("estimated_hours") or 0.0),
                        }
                    )
            update: dict[str, Any] = {"budget_matches": matches}
            if errors:
                update["errors"] = errors
            return update

    return search_budgets


async def generate_estimate(state: EstimationState) -> dict:
    """Consolidate budget_matches per component (median + contingency), then total.

    Median over mean: robust to a single outlier reference, same reasoning as
    the Session 12 ``calculate_estimate``. A component with no matches is
    costed at 0h and flagged, never guessed.
    """
    with logfire.span("node: generate_estimate"):
        by_component: dict[str, list[float]] = {}
        for match in state.get("budget_matches", []):
            by_component.setdefault(match["component"], []).append(match["amount"])

        components_out = []
        total = 0.0
        for component in state.get("components", []):
            name = component["name"]
            amounts = by_component.get(name, [])
            if amounts:
                hours = round(statistics.median(amounts) * (1 + CONTINGENCY_FACTOR), 1)
                unbudgeted = False
            else:
                hours = 0.0
                unbudgeted = True
            total += hours
            components_out.append(
                {
                    "name": name,
                    "estimated_hours": hours,
                    "reference_count": len(amounts),
                    "unbudgeted": unbudgeted,
                }
            )

        total = round(total, 1)
        estimate = {
            "components": components_out,
            "total_hours": total,
            "summary": f"total={total}h across {len(components_out)} components",
        }
        return {"estimate": estimate}


async def validate_and_consolidate(state: EstimationState) -> dict:
    """Guardrails over the finished estimate: coherence + unbudgeted components."""
    with logfire.span("node: validate_and_consolidate"):
        estimate = state.get("estimate") or {}
        components = estimate.get("components", [])
        issues: list[str] = []

        if any(c["unbudgeted"] for c in components):
            issues.append("one or more components have no historical reference")
        computed_total = round(sum(c["estimated_hours"] for c in components), 1)
        if abs(computed_total - estimate.get("total_hours", 0.0)) > _TOTAL_TOLERANCE_HOURS:
            issues.append("total_hours does not match the sum of components")
        if state.get("errors"):
            issues.append(f"{len(state['errors'])} error(s) occurred earlier in the graph")

        status = "needs_review" if issues else "validated"
        return {"status": status, "errors": issues if status == "needs_review" else []}
