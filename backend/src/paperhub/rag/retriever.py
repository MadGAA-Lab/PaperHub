"""Retrieve candidate chunks for paper_qa per SRS §III-5.2."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil

import numpy as np

from paperhub.pipelines.embedder import Embedder, get_embedder
from paperhub.rag.chroma import ChromaStore, ChunkSearchResult
from paperhub.rag.reranker import Reranker, RerankResult, get_reranker


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    paper_content_id: int
    text: str
    score: float


def _candidate_k(corpus_size: int) -> int:
    return min(50, max(10, ceil(corpus_size / 3)))


class Retriever:
    def __init__(
        self,
        chroma: ChromaStore,
        *,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self._chroma = chroma
        self._embedder = embedder or get_embedder()
        self._reranker = reranker or get_reranker()

    def retrieve(
        self,
        query: str,
        *,
        enabled_paper_content_ids: list[int],
        corpus_size: int,
        top_k: int = 10,
    ) -> list[RetrievedChunk]:
        if not enabled_paper_content_ids:
            return []
        cand_k = _candidate_k(corpus_size)
        query_vec: np.ndarray = self._embedder.embed([query])[0]
        candidates: list[ChunkSearchResult] = self._chroma.search(
            query_embedding=query_vec,
            paper_content_ids=enabled_paper_content_ids,
            k=cand_k,
        )
        if not candidates:
            return []
        rerank_in = [c.text for c in candidates]
        reranked: list[RerankResult] = self._reranker.rerank(query, rerank_in, top_k)
        return [
            RetrievedChunk(
                chunk_id=candidates[r.index].chunk_id,
                paper_content_id=candidates[r.index].paper_content_id,
                text=candidates[r.index].text,
                score=r.score,
            )
            for r in reranked
        ]
