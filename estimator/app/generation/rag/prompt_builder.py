"""Prompt construction for grounded estimate generation (Session 9).

The system prompt encodes the grounding policy: every quantitative claim must
trace back to a ``<source>`` block, fabricated ids are forbidden, and when the
context cannot support an estimate the model must say so via
``confidence="insufficient"`` rather than guess.
"""

from __future__ import annotations

from app.generation.rag.schemas import EstimationQuery


def build_system_prompt() -> str:
    """Return the grounding system prompt for the generator."""
    return (
        "You are a senior software-delivery estimator. Produce a cost estimate in "
        "engineer-days for the project described by the user, grounded in historical "
        "budgets supplied as <source> blocks.\n"
        "\n"
        "Rules:\n"
        "1. Base every estimate ONLY on the <source> blocks provided. Do not rely on "
        "outside knowledge for the numbers.\n"
        "2. Cite every quantitative claim with the source id(s) it comes from "
        "(the `id` attribute of the <source> element).\n"
        "3. Never invent source ids. If a needed component has no supporting source, "
        "express it as an Assumption instead of citing a non-existent id.\n"
        "4. Clearly distinguish evidence-backed components (with sources) from "
        "assumptions (without sources).\n"
        "5. If the provided context is insufficient to estimate responsibly, set "
        'confidence="insufficient", leave total_engineer_days and duration_weeks '
        "null, and explain what is missing in insufficient_context_explanation.\n"
        "6. Otherwise set confidence to high/medium/low based on how well the sources "
        "match the project, and explain your derivation in `reasoning`."
    )


def build_user_message(context_block: str, structured_query: EstimationQuery) -> str:
    """Assemble the user turn: the structured brief plus the retrieved sources."""
    brief_lines = [
        f"Function: {structured_query.function}",
        f"Technologies: {', '.join(structured_query.technologies) or 'n/a'}",
        f"Sector: {structured_query.sector or 'n/a'}",
        f"Scale: {structured_query.scale}",
        f"Country: {structured_query.country or 'n/a'}",
        f"Regulations: {', '.join(structured_query.regulations) or 'n/a'}",
        f"Constraints: {', '.join(structured_query.constraints) or 'n/a'}",
    ]
    brief = "\n".join(brief_lines)

    return (
        "<project_brief>\n"
        f"{brief}\n"
        "</project_brief>\n"
        "\n"
        "<sources>\n"
        f"{context_block}\n"
        "</sources>\n"
        "\n"
        "Produce the grounded estimate now, citing source ids for every "
        "quantitative claim."
    )
