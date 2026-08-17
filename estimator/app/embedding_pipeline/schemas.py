"""Typed models for the embedding pipeline.

Input side (``Budget`` / ``BudgetComponent``) mirrors the historical-budget
JSON produced by Session 6. Output side (``Chunk`` / ``EmbeddedChunk``)
carries a fragment ready to embed and, once embedded, its vector plus
aggregate stats for the whole ingest call.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Closed to the sectors present in data/budgets_sample.json. A sector outside
# this set almost certainly means the wrong dataset was sent, so we fail
# validation loudly (422) rather than silently accept an unknown value that
# would later confuse a filter query.
ClientSector = Literal["finance", "ecommerce", "healthcare", "industrial"]
ComponentComplexity = Literal["low", "medium", "high"]


class ClientMetadata(BaseModel):
    name: str = Field(min_length=1, description="Client company name.")
    sector: ClientSector
    country: str = Field(min_length=2, max_length=2, description="ISO 3166-1 alpha-2 code.")


class BudgetComponent(BaseModel):
    """One line item of a historical budget — the unit this exercise chunks."""

    component_id: str = Field(min_length=1, description="Unique within its budget, e.g. 'AUTH-001'.")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    tech_stack: list[str] = Field(default_factory=list)
    estimated_hours: int = Field(ge=0)
    complexity: ComponentComplexity
    dependencies: list[str] = Field(
        default_factory=list, description="component_ids this component depends on."
    )


class Budget(BaseModel):
    budget_id: str = Field(min_length=1)
    client_metadata: ClientMetadata
    project_summary: str = Field(min_length=1)
    main_technology: str = Field(min_length=1)
    year: int = Field(ge=2000, le=2100)
    total_estimated_hours: int = Field(ge=0)
    components: list[BudgetComponent] = Field(min_length=1)


class Chunk(BaseModel):
    """A fragment ready to be embedded.

    ``text`` is the only field sent to the embeddings API. Everything in
    ``metadata`` travels alongside the chunk for future filtering but is
    never itself embedded.
    """

    chunk_id: str = Field(description="'{budget_id}::{component_id}', e.g. 'BUD-2024-014::AUTH-001'.")
    text: str
    metadata: dict = Field(default_factory=dict)
    token_count: int = Field(ge=0, description="tiktoken count of `text` for the embedding model.")


class EmbeddedChunk(Chunk):
    embedding: list[float] = Field(description="Dense vector from the embedding model.")


class IngestRequest(BaseModel):
    budgets: list[Budget] = Field(min_length=1)


class IngestStats(BaseModel):
    total_budgets: int = Field(ge=0)
    total_chunks: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0.0)


class IngestResponse(BaseModel):
    chunks: list[EmbeddedChunk]
    stats: IngestStats
