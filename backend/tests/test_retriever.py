"""Tests for Retriever — all fakes, no real embedder / reranker / chroma."""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from paperhub.rag.chroma import ChromaStore, ChunkSearchResult
from paperhub.rag.reranker import RerankResult, _CrossEncoderReranker
from paperhub.rag.retriever import RetrievedChunk, Retriever, _candidate_k

# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------

class _FakeEmbedder:
    """Returns deterministic 384-dim zero vector, tracking call count."""

    def __init__(self) -> None:
        self._called = False

    def embed(self, texts: list[str]) -> np.ndarray:
        self._called = True
        return np.zeros((len(texts), 384), dtype=np.float32)

    def was_called(self) -> bool:
        return self._called


class _FakeChromaStore:
    """Wraps a preset list of ChunkSearchResults to return from search()."""

    def __init__(self, results: list[ChunkSearchResult]) -> None:
        self._results = results

    # ChromaStore constructor needs persist_dir; override to accept nothing.
    @classmethod
    def create(cls, results: list[ChunkSearchResult]) -> _FakeChromaStore:
        return cls(results)

    def search(
        self,
        *,
        query_embedding: np.ndarray,
        paper_content_ids: list[int],
        k: int,
    ) -> list[ChunkSearchResult]:
        return self._results[:k]

    # Satisfy type-checker: ChromaStore has add_chunks too.
    def add_chunks(self, *args: object, **kwargs: object) -> None:  # pragma: no cover
        pass


def _fake_chroma(results: list[ChunkSearchResult]) -> ChromaStore:
    """Cast _FakeChromaStore to ChromaStore (duck-typing, safe at runtime)."""
    return _FakeChromaStore.create(results)  # type: ignore[return-value]


def _fake_reranker(order: list[int], scores: list[float]) -> _CrossEncoderReranker:
    """Returns a MagicMock whose rerank() emits RerankResults in *order* with *scores*."""
    mock = MagicMock(spec=_CrossEncoderReranker)

    def _rerank(query: str, texts: list[str], top_k: int) -> list[RerankResult]:
        out = [RerankResult(index=i, score=s) for i, s in zip(order, scores, strict=True)]
        return out[:top_k]

    mock.rerank.side_effect = _rerank
    return mock  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# _candidate_k formula
# ---------------------------------------------------------------------------

def test_candidate_k_formula() -> None:
    assert _candidate_k(0) == 10
    assert _candidate_k(10) == 10     # ceil(10/3) = 4 → max(10, 4) = 10
    assert _candidate_k(60) == 20     # ceil(60/3) = 20 → within [10, 50]
    assert _candidate_k(1000) == 50   # ceil(1000/3) = 334 → min(50, 334) = 50


# ---------------------------------------------------------------------------
# Retriever tests
# ---------------------------------------------------------------------------

def test_retrieve_empty_enabled_returns_empty() -> None:
    """retrieve() with no enabled_paper_content_ids returns [] without embedding."""
    embedder = _FakeEmbedder()
    retriever = Retriever(
        _fake_chroma([]),
        embedder=embedder,
        reranker=_fake_reranker([], []),
    )
    results = retriever.retrieve(
        "query",
        enabled_paper_content_ids=[],
        corpus_size=100,
    )
    assert results == []
    assert not embedder._called  # noqa: SLF001


def test_retrieve_no_candidates_returns_empty() -> None:
    """retrieve() skips reranker when chroma search returns empty list."""
    embedder = _FakeEmbedder()
    reranker_mock = MagicMock(spec=_CrossEncoderReranker)

    retriever = Retriever(
        _fake_chroma([]),
        embedder=embedder,
        reranker=reranker_mock,
    )
    results = retriever.retrieve(
        "query",
        enabled_paper_content_ids=[1, 2],
        corpus_size=30,
    )
    assert results == []
    reranker_mock.rerank.assert_not_called()


def test_retrieve_returns_reranked_top_k() -> None:
    """retrieve() assembles RetrievedChunks in reranker order."""
    candidates = [
        ChunkSearchResult(chunk_id=10, paper_content_id=1, text="first", score=0.8),
        ChunkSearchResult(chunk_id=11, paper_content_id=1, text="second", score=0.7),
        ChunkSearchResult(chunk_id=12, paper_content_id=2, text="third", score=0.6),
        ChunkSearchResult(chunk_id=13, paper_content_id=2, text="fourth", score=0.5),
        ChunkSearchResult(chunk_id=14, paper_content_id=1, text="fifth", score=0.4),
    ]
    # Reranker reverses the order: index 4 best, then 2, then 0
    reranker = _fake_reranker(order=[4, 2, 0], scores=[0.95, 0.85, 0.75])

    retriever = Retriever(
        _fake_chroma(candidates),
        embedder=_FakeEmbedder(),
        reranker=reranker,
    )
    results = retriever.retrieve(
        "my query",
        enabled_paper_content_ids=[1, 2],
        corpus_size=15,
        top_k=3,
    )
    assert len(results) == 3
    assert results[0] == RetrievedChunk(
        chunk_id=14, paper_content_id=1, text="fifth", score=0.95
    )
    assert results[1] == RetrievedChunk(
        chunk_id=12, paper_content_id=2, text="third", score=0.85
    )
    assert results[2] == RetrievedChunk(
        chunk_id=10, paper_content_id=1, text="first", score=0.75
    )
