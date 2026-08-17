"""Cross-encoder reranker.

The vector/lexical branches are bi-encoders in spirit: query and document get
scored independently and compared afterwards (cosine distance, ts_rank). A
cross-encoder instead feeds the (query, document) pair through the model
together, so it can attend across both texts at once — much more accurate,
but far too slow to run over the whole corpus. Hence recall-then-rerank: the
cheap branches pull a wide candidate set, the cross-encoder only rescores
those few dozen.

Model is multilingual (handles the Spanish transcripts and English budgets
alike) and small enough for CPU. Loaded lazily so importing this module (or
starting the app) never pulls in torch until a rerank actually happens.
"""

from __future__ import annotations

import threading
import time

import structlog

from app.config import get_settings

log = structlog.get_logger()


class CrossEncoderReranker:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls) -> "CrossEncoderReranker":
        return cls(get_settings().RERANKER_MODEL)

    def load(self) -> None:
        """Force the model to load now (used by verify_reranker.py)."""
        self._model_instance()

    def _model_instance(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            from sentence_transformers import CrossEncoder

            t0 = time.perf_counter()
            self._model = CrossEncoder(self.model_name)
            log.info(
                "reranker_model_loaded",
                model=self.model_name,
                load_ms=int((time.perf_counter() - t0) * 1000),
            )
            return self._model

    def score(self, query: str, documents: list[str]) -> list[float]:
        """One relevance score per document (higher = more relevant)."""
        if not documents:
            return []
        model = self._model_instance()
        t0 = time.perf_counter()
        scores = model.predict([(query, doc) for doc in documents])
        log.info(
            "reranker_scored",
            pairs=len(documents),
            score_ms=int((time.perf_counter() - t0) * 1000),
        )
        return [float(s) for s in scores]

    def rerank(self, query: str, candidates: list, top_n: int, text_of=lambda c: c.content) -> list:
        """Reorder ``candidates`` by cross-encoder score and keep the best ``top_n``."""
        if not candidates:
            return []
        scores = self.score(query, [text_of(c) for c in candidates])
        ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
        return [candidate for candidate, _ in ranked[:top_n]]
