"""Post-generation checks for grounded estimates (Session 9-11).

Two independent guards run after the LLM returns an :class:`Estimate`:

* :func:`verify_citations` — every cited ``chunk_id`` (line-level, per task,
  Session 11) and every top-level ``source_id`` must correspond to a chunk
  that was actually retrieved. A citation pointing at a chunk never handed to
  the LLM is a hallucination wearing the clothes of rigor, not a detail — it
  is flagged as "dangling" and triggers one corrective retry in the
  orchestrator.
* :func:`check_coherence` — the ``insufficient`` confidence level has a strict
  shape (no numbers, an explanation present); a violation is a malformed
  response, not a valid estimate.
"""

from __future__ import annotations

import structlog

from app.generation.rag.schemas import CitationLine, CitationReport, Estimate, RetrievedChunk

log = structlog.get_logger()


def verify_citations(
    estimate: Estimate,
    retrieved_chunks: list[RetrievedChunk],
) -> CitationReport:
    """Classify every task's citation status against the chunks actually retrieved.

    A task line is "insufficient" when the model itself declared
    ``grounded=False`` (no citation to check); otherwise it is "grounded" iff
    every ``chunk_id`` it cites was retrieved, and "dangling" the moment one
    wasn't. The top-level ``Estimate.sources`` citations are checked
    separately and reported in ``top_level_fabricated_ids``.

    Parameters
    ----------
    estimate:
        The generated estimate to inspect.
    retrieved_chunks:
        The chunks the estimate was supposed to be grounded in.

    Returns
    -------
    CitationReport
        Per-task classification plus a flat, de-duplicated list of every
        fabricated chunk id (task-level dangling + top-level), for callers
        that only need a retry-feedback message.
    """
    valid_ids = {chunk.id for chunk in retrieved_chunks}

    lines: list[CitationLine] = []
    dangling_ids: set[int] = set()
    for module in estimate.modules:
        for task in module.tasks:
            if not task.grounded:
                lines.append(
                    CitationLine(module=module.name, task=task.name, status="insufficient")
                )
                continue
            chunk_ids = [source.chunk_id for source in task.sources]
            fabricated = [cid for cid in chunk_ids if cid not in valid_ids]
            dangling_ids.update(fabricated)
            status = "dangling" if fabricated else "grounded"
            lines.append(
                CitationLine(module=module.name, task=task.name, status=status, chunk_ids=chunk_ids)
            )

    top_level_fabricated = sorted({citation.source_id for citation in estimate.sources} - valid_ids)

    report = CitationReport(
        lines=lines,
        top_level_fabricated_ids=top_level_fabricated,
        fabricated_chunk_ids=sorted(dangling_ids | set(top_level_fabricated)),
    )
    if not report.is_clean:
        log.warning(
            "dangling_citations",
            fabricated_chunk_ids=report.fabricated_chunk_ids,
            top_level_fabricated_ids=report.top_level_fabricated_ids,
        )
    return report


def check_coherence(estimate: Estimate) -> bool:
    """Return whether the estimate's confidence level matches its content.

    When ``confidence == "insufficient"``: both numeric totals must be ``None``,
    ``modules`` must be empty, and ``insufficient_context_explanation`` must be
    non-empty. Any other confidence level is always considered coherent here
    (the numeric checks belong to the schema/business rules, not to this guard).
    """
    if estimate.confidence != "insufficient":
        return True
    return (
        estimate.total_engineer_days is None
        and estimate.duration_weeks is None
        and not estimate.modules
        and bool(estimate.insufficient_context_explanation)
    )
