"""Unit tests for post-generation validation (Session 9-11)."""

from __future__ import annotations

from app.generation.rag.schemas import (
    Estimate,
    RetrievedChunk,
    SourceCitation,
    SourceReference,
    TaskItem,
    WorkModule,
)
from app.generation.rag.validation import check_coherence, verify_citations


def _chunk(chunk_id: int) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        content="Component: Auth\nEstimated hours: 120",
        sector="finance",
        project_year=2024,
        chunk_type="budget_component",
        distance=0.3,
    )


def _task(name: str, *, chunk_ids: list[int]) -> TaskItem:
    if not chunk_ids:
        return TaskItem(name=name, grounded=False, sources=[])
    return TaskItem(
        name=name,
        engineer_days=20,
        grounded=True,
        sources=[
            SourceReference(chunk_id=cid, document_id=f"BUD-{cid}", evidence="120 hours")
            for cid in chunk_ids
        ],
    )


def _estimate(
    *, top_level_source_ids: list[int], task_chunk_ids: list[int], confidence="high"
) -> Estimate:
    return Estimate(
        total_engineer_days=20,
        duration_weeks=4,
        modules=[
            WorkModule(name="Authentication", tasks=[_task("Auth", chunk_ids=task_chunk_ids)])
        ],
        sources=[
            SourceCitation(source_id=sid, relevance="primary", used_for="auth")
            for sid in top_level_source_ids
        ],
        assumptions=[],
        confidence=confidence,
        reasoning="Derived from retrieved budgets.",
    )


def test_verify_citations_all_valid_is_clean():
    chunks = [_chunk(1), _chunk(2)]
    estimate = _estimate(top_level_source_ids=[1, 2], task_chunk_ids=[1])
    report = verify_citations(estimate, chunks)
    assert report.is_clean
    assert report.fabricated_chunk_ids == []
    assert report.lines[0].status == "grounded"


def test_verify_citations_flags_dangling_task_line():
    chunks = [_chunk(1), _chunk(2)]
    # Task cites 42, never retrieved — a dangling (hallucinated) citation.
    estimate = _estimate(top_level_source_ids=[1], task_chunk_ids=[42])
    report = verify_citations(estimate, chunks)
    assert not report.is_clean
    assert report.lines[0].status == "dangling"
    assert report.fabricated_chunk_ids == [42]


def test_verify_citations_flags_top_level_fabrication_separately():
    chunks = [_chunk(1)]
    estimate = _estimate(top_level_source_ids=[1, 99], task_chunk_ids=[1])
    report = verify_citations(estimate, chunks)
    assert report.top_level_fabricated_ids == [99]
    assert report.fabricated_chunk_ids == [99]
    assert report.lines[0].status == "grounded"


def test_verify_citations_ungrounded_task_is_insufficient_not_dangling():
    chunks = [_chunk(1)]
    estimate = _estimate(top_level_source_ids=[], task_chunk_ids=[])
    report = verify_citations(estimate, chunks)
    assert report.is_clean
    assert report.lines[0].status == "insufficient"
    assert report.lines[0].chunk_ids == []


def test_verify_citations_empty_retrieval_flags_every_cited_id():
    estimate = _estimate(top_level_source_ids=[1], task_chunk_ids=[2])
    report = verify_citations(estimate, [])
    assert report.fabricated_chunk_ids == [1, 2]
    assert report.lines[0].status == "dangling"


def test_check_coherence_insufficient_with_nulls_is_coherent():
    estimate = Estimate(
        total_engineer_days=None,
        duration_weeks=None,
        confidence="insufficient",
        reasoning="no sources",
        insufficient_context_explanation="No relevant budgets retrieved.",
    )
    assert check_coherence(estimate) is True


def test_check_coherence_insufficient_with_numbers_is_incoherent():
    estimate = Estimate(
        total_engineer_days=10,
        duration_weeks=2,
        confidence="insufficient",
        reasoning="contradiction",
        insufficient_context_explanation="",
    )
    assert check_coherence(estimate) is False


def test_check_coherence_non_insufficient_always_true():
    estimate = _estimate(top_level_source_ids=[1], task_chunk_ids=[1], confidence="low")
    assert check_coherence(estimate) is True
