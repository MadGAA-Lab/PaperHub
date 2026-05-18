"""Lazy-loaded sentence-transformers embedder.

Single process-wide singleton — the model is ~110 MB and instantiating per
call would dominate latency. The first .embed() call loads from the HF cache.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np
from sentence_transformers import SentenceTransformer

from paperhub.config import load_settings


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray:
        ...


class _SentenceTransformersEmbedder:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: SentenceTransformer | None = None

    def _load(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        model = self._load()
        vecs = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return np.asarray(vecs, dtype=np.float32)


_singleton: _SentenceTransformersEmbedder | None = None


def get_embedder() -> Embedder:
    global _singleton
    if _singleton is None:
        settings = load_settings()
        _singleton = _SentenceTransformersEmbedder(settings.embedding_model)
    return _singleton
