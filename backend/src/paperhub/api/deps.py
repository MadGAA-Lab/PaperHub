"""Shared FastAPI dependency helpers."""
from __future__ import annotations

from fastapi import Request

from paperhub.config import Settings
from paperhub.llm.adapter import LlmAdapter
from paperhub.llm.litellm_adapter import LiteLlmAdapter
from paperhub.rag.chroma import ChromaStore


def get_chroma(request: Request, settings: Settings) -> ChromaStore:
    """Return the lifespan-warmed ChromaStore from app.state, or build a
    per-request fallback if app.state isn't set (e.g. in tests where
    ASGITransport bypasses lifespan)."""
    existing = getattr(request.app.state, "chroma", None)
    if isinstance(existing, ChromaStore):
        return existing
    return ChromaStore(settings.chroma_dir)


def get_llm(request: Request) -> LlmAdapter:
    """Return the ``LlmAdapter`` from ``app.state.llm`` if set, else build a
    fresh ``LiteLlmAdapter``.

    Tests inject a stub adapter by assigning to ``app.state.llm`` after
    ``create_app()`` returns. Production code doesn't set it and just gets
    the default LiteLLM adapter (stateless, cheap to construct per-request).
    """
    existing = getattr(request.app.state, "llm", None)
    if existing is not None:
        return existing  # type: ignore[no-any-return]
    return LiteLlmAdapter()
