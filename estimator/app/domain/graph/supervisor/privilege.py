"""Minimum-privilege enforcement + audit trail for the supervisor's agents (Level 3).

Each specialist is allowed exactly one Session 12 tool (or none, for the plain-LLM
extractor). ``call_tool`` is the ONLY way an agent invokes its tool: it checks the
call against ``AGENT_TOOLS`` before running anything, so an agent literally cannot
call a tool it was not assigned — there is no separate code path that skips the
check. Every call, allowed or not, is logged via ``structlog`` and returned as an
``AgentContribution`` the caller appends to the graph's ``agent_contributions``
accumulator, so a full run is reconstructable from the state alone.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import structlog

from app.domain.graph.supervisor.state import AgentContribution

log = structlog.get_logger()

# The declared privilege table: agent name -> the one tool it may call (None = no
# tool, plain LLM reasoning only).
AGENT_TOOLS: dict[str, str | None] = {
    "requirements_extractor": None,
    "budget_searcher": "search_budgets",
    "estimate_generator": "derive_task_hours",
    "coherence_validator": "validate_estimate",
}


class PrivilegeViolation(Exception):
    """Raised when an agent calls a tool outside its declared privilege."""


async def call_tool(
    agent: str,
    tool_name: str,
    fn: Callable[..., Awaitable[Any] | Any],
    *args: Any,
    detail: str | None = None,
    **kwargs: Any,
) -> tuple[Any, AgentContribution]:
    """Run ``fn`` on ``agent``'s behalf only if ``tool_name`` is its declared tool.

    Returns ``(result, contribution)`` on success. Raises ``PrivilegeViolation`` on
    a denied call — the contribution for the denial is attached to the exception
    (``exc.contribution``) so the caller can still record it even though the call
    never ran. A ``fn`` that raises is caught, logged as ``outcome="error"`` and
    re-raised, so the soft-fail policy stays the caller's decision, not this one's.
    """
    allowed = AGENT_TOOLS.get(agent)
    if allowed != tool_name:
        contribution: AgentContribution = {
            "agent": agent,
            "tool": tool_name,
            "outcome": "denied",
            "detail": f"{agent!r} is not privileged to call {tool_name!r} (allowed: {allowed!r})",
        }
        log.warning("supervisor_privilege_denied", **contribution)
        exc = PrivilegeViolation(contribution["detail"])
        exc.contribution = contribution  # type: ignore[attr-defined]
        raise exc

    try:
        result = fn(*args, **kwargs)
        if hasattr(result, "__await__"):
            result = await result
    except Exception as exc:  # noqa: BLE001 — logged + re-raised, caller decides.
        contribution = {
            "agent": agent,
            "tool": tool_name,
            "outcome": "error",
            "detail": f"{tool_name} failed: {exc}"[:300],
        }
        log.error("supervisor_tool_error", **contribution)
        raise

    contribution = {
        "agent": agent,
        "tool": tool_name,
        "outcome": "ok",
        "detail": detail or f"{tool_name} ok",
    }
    log.info("supervisor_tool_call", **contribution)
    return result, contribution
