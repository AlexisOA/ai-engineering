"""The four specialist agents (Level 1) — pure ``state -> partial update`` functions.

Each agent is restricted to at most one Session 12 tool (``app.generation.agentic.
agent_tools``), enforced by ``privilege.call_tool`` (Level 3). Reuses Session 9-13
building blocks rather than re-implementing them:

* ``requirements_extractor`` — same structured-output shape as the Session 13
  pre-exercise ``extract_requirements`` node (``LLMWrapper.complete_structured``).
* ``budget_searcher`` — classifies requirements into components with a plain LLM
  call (not a declared tool — internal reasoning, same as the pre-exercise
  ``classify_components``), then calls the ``search_budgets`` tool once per
  component, exactly as the tool table in the exercise assigns it.
* ``estimate_generator`` — calls ``derive_task_hours`` (the exercise's
  "calculate_estimate") once per component: the SAME distance-weighted consensus
  arithmetic the Session 10 per-task path and the Session 12 agent use. No LLM
  call here — the numbers are deterministic, grounded in the retrieved hours.
* ``coherence_validator`` — calls ``validate_estimate``, the S4-style guardrails
  already used by the Session 12 agent and the Session 13 pre-exercise node.
"""

from __future__ import annotations

import asyncio

import structlog

from app.config import get_settings
from app.domain.graph.schemas import ComponentClassification, RequirementsExtraction
from app.domain.graph.state import BudgetMatch, Component
from app.domain.graph.supervisor.privilege import call_tool
from app.domain.graph.supervisor.state import SupervisorState
from app.generation.agentic import agent_tools
from app.generation.rag.agent_retrieval import make_retrieval_backend
from app.generation.rag.task_hours import distance_weighted_consensus

log = structlog.get_logger()

HOURS_PER_DAY = 8.0

_EXTRACT_SYSTEM_PROMPT = (
    "You are a software-delivery analyst. Read a raw, messy client meeting "
    "transcript and extract a flat list of the concrete requirements the client "
    "wants built. One atomic requirement per item, concise technical English, "
    "regardless of the transcript language. Ignore small talk, anecdotes and "
    "digressions. Never invent requirements the transcript gives no evidence for."
)

_CLASSIFY_SYSTEM_PROMPT = (
    "You are a solution architect. Group a list of project requirements into the "
    "distinct functional COMPONENTS needed to deliver them. Each component has a "
    "short name and a coarse category (e.g. backend, integration, mobile, "
    "analytics, frontend, infrastructure). Merge requirements that belong to the "
    "same component; keep genuinely unrelated pieces separate."
)


def _norm(name: str) -> str:
    return name.split("[", 1)[0].strip().lower()


async def requirements_extractor(state: SupervisorState) -> dict:
    """Transcript -> a flat list of requirements. No tool: plain LLM reasoning."""
    from app.dependencies import get_llm_wrapper

    settings = get_settings()
    wrapper = get_llm_wrapper()
    result, _meta = await asyncio.to_thread(
        wrapper.complete_structured,
        system_prompt=_EXTRACT_SYSTEM_PROMPT,
        user_message=state["transcript"],
        response_model=RequirementsExtraction,
        model_override=settings.GRAPH_EXTRACTION_MODEL,
    )
    requirements = [r.strip() for r in result.requirements if r.strip()]
    contribution = {
        "agent": "requirements_extractor",
        "tool": None,
        "outcome": "ok",
        "detail": f"extracted {len(requirements)} requirements",
    }
    log.info("supervisor_requirements_extractor", requirements=len(requirements))
    return {"requirements": requirements, "agent_contributions": [contribution]}


async def budget_searcher(state: SupervisorState) -> dict:
    """Requirements -> components -> historical budget matches (search_budgets)."""
    from app.dependencies import get_llm_wrapper

    settings = get_settings()
    wrapper = get_llm_wrapper()
    requirements = state.get("requirements") or []
    user_message = "Requirements:\n" + "\n".join(f"- {r}" for r in requirements)
    classification, _meta = await asyncio.to_thread(
        wrapper.complete_structured,
        system_prompt=_CLASSIFY_SYSTEM_PROMPT,
        user_message=user_message,
        response_model=ComponentClassification,
        model_override=settings.GRAPH_EXTRACTION_MODEL,
    )
    components: list[Component] = [
        {"name": c.name.strip(), "category": c.category.strip()}
        for c in classification.components
        if c.name.strip()
    ]

    backend = make_retrieval_backend(
        top_k=settings.AGENT_SEARCH_TOP_K,
        distance_threshold=settings.AGENT_SEARCH_DISTANCE_THRESHOLD,
    )
    matches: list[BudgetMatch] = []
    contributions: list[dict] = []
    errors: list[str] = []
    for component in components:
        query = f"{component['name']} ({component['category']})"
        raw_args = {"query": query, "filters": None}
        try:
            tool_result, contribution = await call_tool(
                "budget_searcher",
                "search_budgets",
                agent_tools.search_budgets,
                raw_args,
                backend=backend,
                detail=f"searched budgets for {component['name']!r}",
            )
        except Exception as exc:  # noqa: BLE001 — soft-fail one component, keep going.
            errors.append(f"search_budgets failed for {component['name']!r}: {exc}")
            contributions.append(
                {
                    "agent": "budget_searcher",
                    "tool": "search_budgets",
                    "outcome": "error",
                    "detail": str(exc)[:200],
                }
            )
            continue
        contributions.append(contribution)
        for item in tool_result.get("items", []):
            hours = item.get("estimated_hours")
            if hours is None:
                continue
            matches.append(
                {
                    "component": component["name"],
                    "reference_budget_id": item.get("budget_id"),
                    "amount": float(hours),
                    "distance": float(item.get("distance", 0.0)),
                }
            )

    if not contributions:
        # No components to search (empty classification) — still record that this
        # agent ran, so the supervisor's "has it run" check does not loop forever.
        contributions.append(
            {
                "agent": "budget_searcher",
                "tool": None,
                "outcome": "ok",
                "detail": "no components classified, nothing to search",
            }
        )

    log.info(
        "supervisor_budget_searcher",
        components=len(components),
        matches=len(matches),
    )
    update: dict = {
        "components": components,
        "budget_matches": matches,
        "agent_contributions": contributions,
    }
    if errors:
        update["errors"] = errors
    return update


async def estimate_generator(state: SupervisorState) -> dict:
    """Budget matches -> per-component hours (derive_task_hours, deterministic)."""
    components = state.get("components") or []
    matches = state.get("budget_matches") or []

    component_estimates: list[dict] = []
    contributions: list[dict] = []
    reliabilities: list[tuple[float, float]] = []  # (hours, reliability) for the weighted mean
    total_days = 0

    for component in components:
        name = component["name"]
        neighbors = [
            {
                "estimated_hours": int(m["amount"]),
                "distance": m["distance"],
                "source_id": None,
                "budget_id": m.get("reference_budget_id"),
            }
            for m in matches
            if _norm(m["component"]) == _norm(name)
        ]
        raw_args = {"module": "project", "task": name, "neighbors": neighbors}
        result, contribution = await call_tool(
            "estimate_generator",
            "derive_task_hours",
            agent_tools.derive_task_hours,
            raw_args,
            consensus_fn=distance_weighted_consensus,
            detail=f"derived hours for {name!r}",
        )
        contributions.append(contribution)

        hours = result.get("estimated_hours")
        days = round(hours / HOURS_PER_DAY) if hours is not None else None
        if days is not None:
            # Sum the ROUNDED per-component days, not the raw hours: the guardrail
            # in coherence_validator compares total_engineer_days against the sum of
            # engineer_days it can see, so the total must be built from the same
            # rounded numbers or a rounding drift trips a false "totals don't match".
            total_days += days
            reliabilities.append((float(hours), float(result.get("reliability") or 0.0)))
        component_estimates.append(
            {
                "name": name,
                "engineer_days": days,
                "rationale": result.get("summary", ""),
            }
        )

    if not contributions:
        # No components to estimate — still record that this agent ran (see the
        # same guard in budget_searcher: "has it run" must not depend on output size).
        contributions.append(
            {
                "agent": "estimate_generator",
                "tool": None,
                "outcome": "ok",
                "detail": "no components to estimate",
            }
        )

    weighted_reliability = 0.0
    if reliabilities:
        hour_sum = sum(h for h, _r in reliabilities)
        weighted_reliability = sum(h * r for h, r in reliabilities) / hour_sum if hour_sum else 0.0

    estimate = {
        "components": component_estimates,
        "total_engineer_days": total_days,
    }
    log.info(
        "supervisor_estimate_generator",
        components=len(component_estimates),
        total_engineer_days=estimate["total_engineer_days"],
        confidence=round(weighted_reliability, 3),
    )
    return {
        "estimate": estimate,
        "confidence": round(weighted_reliability, 3),
        "agent_contributions": contributions,
    }


async def coherence_validator(state: SupervisorState) -> dict:
    """Run the S4-style guardrails over the estimate (validate_estimate).

    ``validate_estimate``'s arg schema calls the field ``estimated_hours`` (it was
    written for the Session 12 hours-recovery loop) but the check is unit-agnostic
    range arithmetic, so passing engineer-DAYS consistently in both
    ``estimated_hours`` and ``reference_amounts`` is correct — only the label is a
    leftover from S12, not the math.
    """
    estimate = state.get("estimate") or {}
    matches = state.get("budget_matches") or []

    components_arg = []
    for component in estimate.get("components", []):
        name = component["name"]
        days = component.get("engineer_days")
        refs_days = [
            m["amount"] / HOURS_PER_DAY for m in matches if _norm(m["component"]) == _norm(name)
        ]
        components_arg.append(
            {
                "name": name,
                "estimated_hours": days if days is not None else 0,
                "reference_amounts": refs_days,
            }
        )
    raw_args = {
        "components": components_arg,
        "total_hours": estimate.get("total_engineer_days") or 0,
    }
    result, contribution = await call_tool(
        "coherence_validator",
        "validate_estimate",
        agent_tools.validate_estimate,
        raw_args,
        detail="validated the consolidated estimate",
    )
    validation = {"ok": result["ok"], "issues": result["issues"]}
    status = "validated" if validation["ok"] else "needs_review"
    log.info("supervisor_coherence_validator", status=status, issues=len(validation["issues"]))
    return {
        "validation": validation,
        "status": status,
        "agent_contributions": [contribution],
    }
