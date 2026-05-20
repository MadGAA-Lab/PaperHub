import numpy as np

from paperhub.pipelines.embedder import get_embedder


def test_embedder_singleton_returns_same_instance() -> None:
    a = get_embedder()
    b = get_embedder()
    assert a is b


def test_embedder_produces_384_dim_vectors() -> None:
    emb = get_embedder()
    vecs = emb.embed(["hello world", "mixture of experts"])
    assert vecs.shape == (2, 384)
    # Normalized magnitudes ≈ 1.
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3)
