"""Unit tests for the LLM-based PDF title extraction fallback.

Stubs the ``LlmAdapter`` Protocol so no real LiteLLM / Gemini call ever
happens — the helper's contract is what's under test (sanitisation, clip,
exception swallowing, null handling), NOT the adapter wire format."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from paperhub.pipelines.title_extract import (
    PaperTitleResult,
    llm_extract_title,
)

T = TypeVar("T", bound=BaseModel)


class _StubAdapter:
    """Hand-rolled LlmAdapter stub.

    Records the last ``variables`` dict passed to ``structured`` so tests
    can assert on the page-1-text clipping behaviour. Returns a
    configurable ``PaperTitleResult`` (or raises) per the test scenario.
    """

    def __init__(
        self,
        *,
        result: PaperTitleResult | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._result = result
        self._raise_exc = raise_exc
        self.last_variables: dict[str, Any] | None = None
        self.call_count = 0

    async def structured(
        self,
        *,
        slot: str,
        variables: dict[str, Any],
        response_model: type[T],
        model: str,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> T:
        self.call_count += 1
        self.last_variables = variables
        if self._raise_exc is not None:
            raise self._raise_exc
        assert self._result is not None
        # The helper always asks for PaperTitleResult; cast through Any to
        # satisfy the protocol's generic without dragging in mypy gymnastics.
        return self._result  # type: ignore[return-value]

    def stream(
        self,
        *,
        slot: str,
        variables: dict[str, Any],
        model: str,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        raise NotImplementedError("stream is not exercised by title_extract")


@pytest.mark.asyncio
async def test_happy_path_returns_title() -> None:
    """Stub returns a plausible title → helper returns it verbatim."""
    adapter = _StubAdapter(result=PaperTitleResult(title="Real Title"))
    out = await llm_extract_title(adapter, "gemini/gemini-2.5-flash", "page-1 text")
    assert out == "Real Title"
    assert adapter.call_count == 1


@pytest.mark.asyncio
async def test_null_title_returns_empty() -> None:
    """Model judged the page-1 text non-paper / no title → helper returns ""."""
    adapter = _StubAdapter(result=PaperTitleResult(title=None))
    out = await llm_extract_title(
        adapter, "gemini/gemini-2.5-flash", "shopping list",
    )
    assert out == ""


@pytest.mark.asyncio
async def test_adapter_raises_returns_empty_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Any exception from the adapter is swallowed → "" + WARNING logged."""
    adapter = _StubAdapter(raise_exc=RuntimeError("quota exceeded"))
    with caplog.at_level(logging.WARNING, logger="paperhub.pipelines.title_extract"):
        out = await llm_extract_title(adapter, "gemini/gemini-2.5-flash", "text")
    assert out == ""
    assert any(
        "title_extract: LLM call failed" in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_stock_placeholder_sanitised_to_empty() -> None:
    """Even if the LLM returns ``"Untitled"`` or similar stock placeholder,
    ``_sanitise_pdf_title`` rejects it → helper returns ""."""
    adapter = _StubAdapter(result=PaperTitleResult(title="Untitled"))
    out = await llm_extract_title(adapter, "gemini/gemini-2.5-flash", "text")
    assert out == ""


@pytest.mark.asyncio
async def test_page1_text_clipped_before_send() -> None:
    """A page-1 text longer than the 8000-char ceiling must be clipped
    BEFORE it ever hits the adapter — defence against pathological PDFs
    blowing up the token budget."""
    huge_text = "x" * 20000
    adapter = _StubAdapter(result=PaperTitleResult(title="OK"))
    out = await llm_extract_title(adapter, "gemini/gemini-2.5-flash", huge_text)
    assert out == "OK"
    assert adapter.last_variables is not None
    sent = adapter.last_variables["page1_text"]
    assert len(sent) == 8000
    assert sent == "x" * 8000
