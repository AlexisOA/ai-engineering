"""Reciprocal Rank Fusion — merge two independently-ordered rankings into one.

Vector distance and lexical ``ts_rank_cd`` are not on the same scale (one is
"lower is better", the other "higher is better", and neither is bounded the
same way), so averaging the raw scores would be arbitrary. RRF sidesteps that
by only looking at each branch's *rank order*: a chunk's fused score is the
sum of ``1 / (k + rank)`` across every ranking it shows up in. A chunk near
the top of both branches wins; a chunk that only one branch liked still gets
some credit, just less.
"""

from __future__ import annotations

DEFAULT_K = 60  # smoothing constant from the original RRF paper (Cormack et al.)


def reciprocal_rank_fusion(
    rankings: list[list[int]], k: int = DEFAULT_K
) -> list[tuple[int, float]]:
    """Fuse ranked id lists (best-first) into one, sorted best-first.

    A ranking that found nothing contributes an empty list. Duplicate ids
    inside one ranking only count their first (best) position.
    """
    if k <= 0:
        raise ValueError("k must be positive")

    scores: dict[int, float] = {}
    for ranking in rankings:
        seen: set[int] = set()
        for position, item_id in enumerate(ranking):
            if item_id in seen:
                continue
            seen.add(item_id)
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + position)

    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
