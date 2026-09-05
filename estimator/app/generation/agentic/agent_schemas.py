"""Pydantic models for the hand-rolled agent loop (Session 12).

The agent decomposes a transcript into components, searches historical budgets
per component, calculates an estimate and (optionally) validates it — over a
manual loop on the Responses API. These models carry the loop's trace and its
final structured output.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AgentTraceStep(BaseModel):
    """One iteration of the reason -> act -> observe loop."""

    step: int = Field(ge=1)
    reasoning: str = Field(description="What the agent decided at this step and why.")
    action: str = Field(
        description="The tool call rendered as a signature, e.g. "
        'search_budgets(query="...", filters={...}).'
    )
    observation: str = Field(description="Summary of what the tool call returned.")


class AgentComponentEstimate(BaseModel):
    """One component's costed line in the final estimate."""

    name: str
    estimated_hours: float = Field(ge=0)
    reference_count: int = Field(ge=0, description="Historical items the estimate drew from.")
    unbudgeted: bool = Field(
        description="True when no historical reference was found for this "
        "component (estimated_hours is 0, not invented)."
    )
    rationale: str | None = Field(default=None, description="Short explanation of the estimate.")


class AgentEstimate(BaseModel):
    """Final structured output of the agent — the terminal Responses API parse."""

    components: list[AgentComponentEstimate]
    total_hours: float = Field(ge=0)
    confidence: Literal["high", "medium", "low", "insufficient"]
    assumptions: list[str] = Field(default_factory=list)
    summary: str = Field(description="One-paragraph human-readable summary of the estimate.")


class AgentRunResult(BaseModel):
    """Everything one agent run produces: the estimate plus its full trace."""

    estimate: AgentEstimate
    trace: list[AgentTraceStep]
    iterations: int = Field(ge=0)
    stopped_reason: Literal["completed", "max_iterations"]
