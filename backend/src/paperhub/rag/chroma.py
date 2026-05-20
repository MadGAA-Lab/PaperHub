"""Chroma vector store wrapper. One persistent collection per workspace
(`paper_chunks`), metadata-filtered by `paper_content_id`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import chromadb
import numpy as np

# Chroma's rust binding caps a single .add() call at 5461 records per
# batch (observed empirically: 29891 chunks for MolmoACT2 → InternalError
# "Batch size of 29891 is greater than max batch size of 5461"). We
# split client-side to stay below this. Keeping a buffer (4096) below
# the observed cap protects against minor cap changes between Chroma
# versions.
_MAX_BATCH = 4096


@dataclass(frozen=True)
class ChunkSearchResult:
    chunk_id: int
    paper_content_id: int
    text: str
    score: float


class ChromaStore:
    def __init__(self, persist_dir: Path) -> None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._coll = self._client.get_or_create_collection(
            name="paper_chunks",
            metadata={"hnsw:space": "cosine"},
        )

    def add_chunks(
        self,
        paper_content_id: int,
        chunk_ids: list[int],
        texts: list[str],
        embeddings: np.ndarray,
    ) -> None:
        n = len(chunk_ids)
        if n == 0:
            return
        # Split into ``_MAX_BATCH``-sized slices to stay under Chroma's
        # per-call cap. Most papers fit in one batch (a few hundred to
        # ~2000 chunks); large papers like MolmoACT2 produced 29891
        # chunks which is well over the 5461 cap.
        embeddings_list = embeddings.tolist()
        for start in range(0, n, _MAX_BATCH):
            end = min(start + _MAX_BATCH, n)
            self._coll.add(
                ids=[str(cid) for cid in chunk_ids[start:end]],
                documents=texts[start:end],
                embeddings=embeddings_list[start:end],
                metadatas=[
                    {"paper_content_id": paper_content_id}
                    for _ in range(end - start)
                ],
            )

    def delete_paper(self, paper_content_id: int) -> None:
        """Remove every chunk vector belonging to `paper_content_id`.

        Used by `DELETE /papers/content/{id}` (test-friendly library purge).
        No-op if no vectors exist for that paper.
        """
        self._coll.delete(where={"paper_content_id": paper_content_id})

    def search(
        self,
        *,
        query_embedding: np.ndarray,
        paper_content_ids: list[int],
        k: int,
    ) -> list[ChunkSearchResult]:
        if not paper_content_ids or k <= 0:
            return []
        # chromadb's $in filter requires list[str | int | float | bool]
        ids_filter: list[str | int | float | bool] = list(paper_content_ids)
        result = self._coll.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=k,
            where={"paper_content_id": {"$in": ids_filter}},  # type: ignore[dict-item]
        )
        # result fields are list[list[...]] | None; with a single query embedding
        # we always index [0].  cast() avoids the None branch without runtime cost.
        raw_ids = cast(list[list[str]], result.get("ids") or [[]])
        raw_docs = cast(list[list[str]], result.get("documents") or [[]])
        raw_metas = cast(
            list[list[dict[str, str | int | float | bool]]],
            result.get("metadatas") or [[]],
        )
        raw_dists = cast(list[list[float]], result.get("distances") or [[]])
        out: list[ChunkSearchResult] = []
        for i, doc, meta, dist in zip(
            raw_ids[0], raw_docs[0], raw_metas[0], raw_dists[0], strict=True
        ):
            out.append(
                ChunkSearchResult(
                    chunk_id=int(i),
                    paper_content_id=int(meta["paper_content_id"]),
                    text=doc,
                    score=1.0 - float(dist),  # cosine distance → similarity
                )
            )
        return out
