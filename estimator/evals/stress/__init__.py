"""CAG stress test for the Session 6 pre-exercise.

Quantifies where the multi-turn, cache-augmented estimator (built through
Session 5: sliding window, anchors, cumulative summary, ProjectMetadata,
dynamic tier) starts to break under load, before RAG is introduced as the
fix in the live session.

Submodules:

- ``scenarios`` — synthetic 20-turn conversations (growing / pivot /
  contradiction), each declaring the facts a later turn should still recall.
- ``metrics``   — ``LatencyBudgetMetric``, ``CostBudgetMetric``,
  ``MemoryDriftMetric``, evaluated against ``TurnObservation`` and session
  snapshots rather than ``EstimationResult`` (see ``evals.metrics`` for the
  golden-set metrics).
- ``run``       — CLI that drives scenarios x attachment sizes x repeats
  against a live estimator and writes ``results.csv``.
- ``fixtures``  — deterministic PDF generator for the attachment sweep.
"""
