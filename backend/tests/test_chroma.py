from pathlib import Path

import numpy as np
import pytest

from paperhub.rag.chroma import ChromaStore


def test_add_then_search_returns_matching_chunks(tmp_path: Path) -> None:
    store = ChromaStore(tmp_path)
    vecs = np.random.RandomState(42).randn(3, 384).astype(np.float32)
    # Normalize so cosine-sim behaves.
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)

    store.add_chunks(
        paper_content_id=1,
        chunk_ids=[10, 11, 12],
        texts=["alpha", "beta", "gamma"],
        embeddings=vecs,
    )

    results = store.search(query_embedding=vecs[0], paper_content_ids=[1], k=2)
    assert len(results) == 2
    # First match should be the query itself.
    assert results[0].chunk_id == 10
    assert results[0].text == "alpha"


def test_search_filters_by_paper_content_id(tmp_path: Path) -> None:
    store = ChromaStore(tmp_path)
    vecs = np.random.RandomState(0).randn(2, 384).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    store.add_chunks(1, [10], ["paper1"], vecs[:1])
    store.add_chunks(2, [20], ["paper2"], vecs[1:])

    results = store.search(query_embedding=vecs[1], paper_content_ids=[1], k=5)
    assert len(results) == 1
    assert results[0].chunk_id == 10  # Only paper 1 returned despite paper 2 being closer.


def test_add_chunks_splits_batches_larger_than_chroma_cap(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Regression: Chroma's rust binding caps a single .add() call at
    ~5461 records (observed: 29891-chunk MolmoACT2 ingest crashed with
    `Batch size of 29891 is greater than max batch size of 5461`). The
    store must split client-side. Verifies the underlying collection's
    .add() is invoked multiple times when N exceeds the cap, and the
    final corpus is queryable (every record landed)."""
    from paperhub.rag import chroma as chroma_mod

    # Force a tiny cap so the test is fast — 4 records → 2 batches at
    # cap=2. The real cap is 4096; the splitting logic is identical.
    monkeypatch.setattr(chroma_mod, "_MAX_BATCH", 2)

    store = ChromaStore(tmp_path)
    n = 5
    vecs = np.random.RandomState(99).randn(n, 384).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)

    # Count actual .add() invocations on the underlying collection.
    add_calls = {"n": 0}
    real_add = store._coll.add  # noqa: SLF001

    def _spy_add(**kwargs: object) -> object:
        add_calls["n"] += 1
        return real_add(**kwargs)  # type: ignore[arg-type]

    store._coll.add = _spy_add  # type: ignore[method-assign,assignment]  # noqa: SLF001

    store.add_chunks(
        paper_content_id=7,
        chunk_ids=list(range(100, 100 + n)),
        texts=[f"text {i}" for i in range(n)],
        embeddings=vecs,
    )

    # n=5 with cap=2 → 3 batches (2, 2, 1)
    assert add_calls["n"] == 3, (
        f"expected 3 batched .add() calls; got {add_calls['n']}"
    )
    # Every record landed and is queryable.
    results = store.search(query_embedding=vecs[0], paper_content_ids=[7], k=n)
    assert len(results) == n
    assert {r.chunk_id for r in results} == set(range(100, 100 + n))
