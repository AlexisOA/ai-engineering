"""The agent's two (+1) tools (Session 12): schemas, implementations, dispatch.

``search_budgets`` wraps whatever historical-budget retrieval is injected as a
``RetrievalBackend`` — this module never imports ``app.generation.rag`` directly.
That composition (real hybrid+rerank retrieval, or the offline stub) is wired by
the composition root (``app.dependencies``), not here: ``generation/<x>/*`` may
not import a `generation` sibling (see ``ARCHITECTURE.md``), so the backend is
injected the same way ``agentic/boss.py`` already injects ``ActorCallable``/
``CriticCallable`` rather than importing the Actor/Critic's own dependencies.

``calculate_estimate`` and ``validate_estimate`` are pure Python — no LLM call.

Tool schemas are FLAT, per the Responses API (``type``/``name``/``parameters`` at
the top level, not nested under a ``function`` key like Chat Completions), with
``strict: true`` — which requires ``additionalProperties: false`` and every
property listed in ``required`` (optional fields are modeled as nullable instead
of omitted).
"""

from __future__ import annotations

import statistics
from typing import Any, Awaitable, Callable

# A component or requirement description -> historical items in the shape
# {"id", "content_preview", "sector", "budget_id", "estimated_hours", "distance"}
# (see exercises/session-12/reference_retrieval.py for the canonical shape).
# Async so the real backend can await the pipeline's own async retrieve() without
# nesting a second event loop inside the (already async) agent loop.
RetrievalBackend = Callable[[str, "dict[str, Any] | None"], Awaitable[list[dict[str, Any]]]]

# Flat buffer added to every component's central historical estimate. Transparent
# by design — no hidden multipliers stacked on top of each other.
CONTINGENCY_FACTOR = 0.15

# A component's estimate is flagged if it strays this far from its own historical
# references — catches a contingency-inflated or garbled number before it ships.
_RANGE_LOW_MULTIPLIER = 0.3
_RANGE_HIGH_MULTIPLIER = 3.0
_TOTAL_TOLERANCE_HOURS = 0.5

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_budgets",
        "description": (
            "Search historical project budgets for ONE specific component or "
            "requirement (e.g. 'OAuth2 authentication backend', 'SAP ERP "
            "integration'). Call it once per distinct component you identify in "
            "the transcript — never bundle several components into one query, "
            "the historical hours would no longer be comparable. Returns the "
            "matching historical items with their recorded engineer-hours, which "
            "you then pass into calculate_estimate as that component's "
            "reference_amounts. Returns an empty list when nothing matches — "
            "that is a valid, informative result, not an error: try a broader or "
            "differently-worded query before giving up on that component."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A specific, technical description of the ONE component "
                    "to search for (technology, function, scale) — not the whole project.",
                },
                "filters": {
                    "type": ["object", "null"],
                    "description": "Optional narrowing filters. Pass null when you don't "
                    "want to filter.",
                    "properties": {
                        "sectors": {
                            "type": ["array", "null"],
                            "items": {"type": "string"},
                            "description": "Restrict to these client sectors (e.g. "
                            "'logistics', 'finance'). Null = no sector filter.",
                        },
                        "component_type": {
                            "type": ["string", "null"],
                            "description": "A short free-text tag for the kind of "
                            "component (e.g. 'backend/API', 'mobile app', 'ERP "
                            "integration'). Null = no filter.",
                        },
                    },
                    "required": ["sectors", "component_type"],
                    "additionalProperties": False,
                },
            },
            "required": ["query", "filters"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "calculate_estimate",
        "description": (
            "Deterministically cost a set of components from the historical "
            "reference hours you gathered via search_budgets, and total them. "
            "Pass EVERY component you identified, even one with an empty "
            "reference_amounts list (it will be costed as 0h and flagged "
            "'unbudgeted' rather than silently dropped) — never invent an hours "
            "figure yourself, this tool is the only source of numbers. Call it "
            "once, after you have searched every component, not incrementally."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "description": "Every component identified in the transcript.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Short human-readable component name.",
                            },
                            "reference_amounts": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "Recorded engineer-hours from the historical "
                                "items search_budgets returned for this component. Empty "
                                "list if nothing matched.",
                            },
                        },
                        "required": ["name", "reference_amounts"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["components"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "validate_estimate",
        "description": (
            "Run guardrail checks over a finished estimate before you report it: "
            "flags components with no historical reference, an hours figure far "
            "outside its own historical range, or a total that doesn't match the "
            "sum of its components. Call it once, as the LAST step before your "
            "final answer, on the exact components/total calculate_estimate "
            "returned. A failing check is not fatal — it's a signal you may want "
            "to search again or explain the caveat in your final assumptions."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "estimated_hours": {"type": "number"},
                            "reference_amounts": {
                                "type": "array",
                                "items": {"type": "number"},
                            },
                        },
                        "required": ["name", "estimated_hours", "reference_amounts"],
                        "additionalProperties": False,
                    },
                },
                "total_hours": {"type": "number"},
            },
            "required": ["components", "total_hours"],
            "additionalProperties": False,
        },
    },
]


async def search_budgets(args: dict[str, Any], *, backend: RetrievalBackend) -> dict[str, Any]:
    """Retrieve historical items for one component via the injected backend."""
    items = await backend(args["query"], args.get("filters"))
    return {"items": items, "count": len(items)}


def calculate_estimate(args: dict[str, Any]) -> dict[str, Any]:
    """Cost each component from its historical reference hours, then total.

    The median is used (not the mean): it is robust to a single outlier budget,
    which is exactly the failure mode a handful of historical references is
    prone to. A component with no references is never assigned invented hours —
    it is costed at 0 and flagged ``unbudgeted`` so the caller notices.
    """
    breakdown: list[dict[str, Any]] = []
    total = 0.0

    for component in args["components"]:
        name = component["name"]
        refs = component.get("reference_amounts") or []

        if refs:
            central = statistics.median(refs)
            hours = round(central * (1 + CONTINGENCY_FACTOR), 1)
            unbudgeted = False
        else:
            hours = 0.0
            unbudgeted = True

        total += hours
        breakdown.append(
            {
                "name": name,
                "reference_count": len(refs),
                "estimated_hours": hours,
                "unbudgeted": unbudgeted,
            }
        )

    total = round(total, 1)
    return {
        "components": breakdown,
        "total_hours": total,
        "summary": f"total={total}h across {len(breakdown)} components",
    }


def validate_estimate(args: dict[str, Any]) -> dict[str, Any]:
    """S4-style guardrails over a finished estimate: coherence + reasonable ranges."""
    components = args["components"]
    total_hours = args["total_hours"]
    issues: list[str] = []

    computed_total = round(sum(c["estimated_hours"] for c in components), 1)
    if abs(computed_total - total_hours) > _TOTAL_TOLERANCE_HOURS:
        issues.append(
            f"total_hours ({total_hours}) does not match the sum of components ({computed_total})"
        )

    for component in components:
        name = component["name"]
        hours = component["estimated_hours"]
        refs = component.get("reference_amounts") or []

        if not refs:
            issues.append(f"'{name}' has no historical reference (unbudgeted)")
            continue
        if hours <= 0:
            issues.append(f"'{name}' has non-positive estimated_hours ({hours})")
            continue
        if hours < _RANGE_LOW_MULTIPLIER * min(refs) or hours > _RANGE_HIGH_MULTIPLIER * max(refs):
            issues.append(
                f"'{name}' estimated_hours ({hours}) is far outside its historical range {refs}"
            )

    passed = not issues
    summary = "estimate passed all guardrails" if passed else f"{len(issues)} issue(s) found"
    return {"passed": passed, "issues": issues, "summary": summary}


async def dispatch_tool(
    name: str, arguments: dict[str, Any], *, backend: RetrievalBackend
) -> dict[str, Any]:
    """Route a Responses API function_call to its implementation by name."""
    if name == "search_budgets":
        return await search_budgets(arguments, backend=backend)
    if name == "calculate_estimate":
        return calculate_estimate(arguments)
    if name == "validate_estimate":
        return validate_estimate(arguments)
    raise ValueError(f"Unknown tool: {name}")
