"""Tests for the cross-encoder reranker (fast — no real model download)."""
from __future__ import annotations

from unittest.mock import MagicMock

from paperhub.rag.reranker import RerankResult, _CrossEncoderReranker, get_reranker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reranker_with_fake_model(scores: list[float]) -> _CrossEncoderReranker:
    """Return a _CrossEncoderReranker whose _load() returns a stub model."""
    reranker = _CrossEncoderReranker("fake-model")
    fake_model = MagicMock()
    fake_model.predict.return_value = scores
    # Inject the fake model directly so _load() won't try to download anything.
    reranker._model = fake_model  # noqa: SLF001
    return reranker


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_rerank_empty_returns_empty() -> None:
    """rerank() with an empty texts list must return [] without loading model."""
    reranker = _CrossEncoderReranker("never-downloaded")
    # If _load() were called it would attempt a download → test would hang/fail.
    result = reranker.rerank("query", [], top_k=5)
    assert result == []


def test_rerank_orders_by_score_descending() -> None:
    """rerank() returns results sorted by score descending."""
    reranker = _make_reranker_with_fake_model([0.1, 0.9, 0.5])
    results = reranker.rerank("query", ["a", "b", "c"], top_k=2)
    assert results == [
        RerankResult(index=1, score=0.9),
        RerankResult(index=2, score=0.5),
    ]


def test_rerank_respects_top_k() -> None:
    """top_k=1 returns only the single highest-scoring item."""
    reranker = _make_reranker_with_fake_model([0.1, 0.9, 0.5])
    results = reranker.rerank("query", ["a", "b", "c"], top_k=1)
    assert len(results) == 1
    assert results[0] == RerankResult(index=1, score=0.9)


def test_get_reranker_returns_singleton() -> None:
    """get_reranker() must return the same object on every call."""
    # Reset singleton for test isolation.
    import paperhub.rag.reranker as _mod

    _mod._singleton = None  # noqa: SLF001
    try:
        a = get_reranker()
        b = get_reranker()
        assert a is b
    finally:
        # Clean up so other test modules see a fresh state.
        _mod._singleton = None  # noqa: SLF001
