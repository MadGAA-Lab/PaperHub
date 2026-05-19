"""Lazy-loaded cross-encoder reranker (ms-marco-MiniLM by default)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sentence_transformers import CrossEncoder

from paperhub.config import load_settings
from paperhub.pipelines._device import resolve_device


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float


@runtime_checkable
class Reranker(Protocol):
    """Public interface for all reranker implementations.

    Mirrors the Embedder Protocol pattern so retriever.py can depend on this
    public type instead of the private _CrossEncoderReranker class.
    """

    def rerank(self, query: str, texts: list[str], top_k: int) -> list[RerankResult]:
        ...


class _CrossEncoderReranker:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: CrossEncoder | None = None

    def _load(self) -> CrossEncoder:
        if self._model is None:
            self._model = CrossEncoder(self._model_name, device=resolve_device())
        return self._model

    def rerank(self, query: str, texts: list[str], top_k: int) -> list[RerankResult]:
        if not texts:
            return []
        model = self._load()
        # CrossEncoder.predict accepts list[str | list[str]] at runtime despite
        # strict type stubs; cast suppresses the variance mismatch.
        pairs: list[str | list[str]] = [[query, t] for t in texts]
        scores = model.predict(pairs)  # type: ignore[arg-type]
        ranked = sorted(enumerate(scores), key=lambda x: float(x[1]), reverse=True)
        return [RerankResult(index=i, score=float(s)) for i, s in ranked[:top_k]]


_singleton: _CrossEncoderReranker | None = None


def get_reranker() -> Reranker:
    global _singleton
    if _singleton is None:
        settings = load_settings()
        _singleton = _CrossEncoderReranker(settings.reranker_model)
    return _singleton
