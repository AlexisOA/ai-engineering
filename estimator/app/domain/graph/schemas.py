"""Pydantic response models for the graph's two LLM-backed nodes.

Kept separate from ``state.py``'s ``TypedDict``s: Instructor/LiteLLM structured
output needs a Pydantic ``response_model``, while the graph state itself is a
plain ``TypedDict`` (LangGraph's own contract).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RequirementsList(BaseModel):
    requirements: list[str] = Field(
        description="Atomic, one-sentence requirements extracted from the transcript, "
        "in the order they were mentioned."
    )


class ComponentOut(BaseModel):
    name: str = Field(description="Short human-readable component name.")
    category: str = Field(
        description="A short functional category, e.g. 'backend', 'integration', "
        "'mobile', 'analytics', 'infrastructure'."
    )


class ComponentsList(BaseModel):
    components: list[ComponentOut]


class GraphEstimateRequest(BaseModel):
    transcript: str = Field(min_length=100, max_length=50_000)
    estimation_id: str | None = Field(
        default=None,
        description="Used as the checkpointer thread_id; a uuid4 is minted if omitted.",
    )


class GraphEstimateResponse(BaseModel):
    estimate: dict | None
    status: str | None
    errors: list[str] = Field(default_factory=list)
