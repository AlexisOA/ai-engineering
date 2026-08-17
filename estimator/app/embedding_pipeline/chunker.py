"""Structural chunker: one budget component = one chunk.

No overlap, no fixed-size splitting of long descriptions. The JSON structure
already gives us a natural, semantically coherent unit (a component); trusting
it means an unusually long description shows up as a large ``token_count``
instead of being silently sliced mid-sentence — a signal worth surfacing, not
hiding.

Every chunk's text is prefixed with the parent budget's context (project
summary, sector, year, main stack) before the component detail. Without that
header, a component named "Authentication backend" would embed with no trace
of which client or sector it belongs to — this is the "contextual chunk
header" idea from the async material's chunking article.
"""

from __future__ import annotations

import tiktoken

from app.embedding_pipeline.schemas import Budget, BudgetComponent, Chunk

# Resolved once at import time — building a tiktoken encoding per chunk would
# be needless repeated work across a whole ingest call.
_TOKEN_MODEL = "text-embedding-3-small"
_encoding = tiktoken.encoding_for_model(_TOKEN_MODEL)


class JSONStructuralChunker:
    """Turns a list of budgets into one :class:`Chunk` per component."""

    def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        return [
            self._to_chunk(budget, component)
            for budget in budgets
            for component in budget.components
        ]

    def _to_chunk(self, budget: Budget, component: BudgetComponent) -> Chunk:
        text = self._render(budget, component)
        return Chunk(
            chunk_id=f"{budget.budget_id}::{component.component_id}",
            text=text,
            token_count=len(_encoding.encode(text)),
            metadata={
                "budget_id": budget.budget_id,
                "component_id": component.component_id,
                "client_sector": budget.client_metadata.sector,
                "main_technology": budget.main_technology,
                "year": budget.year,
                "complexity": component.complexity,
                "estimated_hours": component.estimated_hours,
            },
        )

    @staticmethod
    def _render(budget: Budget, component: BudgetComponent) -> str:
        header = (
            f"[Project: {budget.project_summary}]\n"
            f"[Client sector: {budget.client_metadata.sector} | "
            f"Year: {budget.year} | Main tech: {budget.main_technology}]"
        )
        body = (
            f"Component: {component.name}\n"
            f"Description: {component.description}\n"
            f"Tech stack: {', '.join(component.tech_stack)}\n"
            f"Complexity: {component.complexity}\n"
            f"Estimated hours: {component.estimated_hours}"
        )
        return f"{header}\n\n{body}"
