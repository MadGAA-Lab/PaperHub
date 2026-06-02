"""F4.5 talk-title synthesizer unit tests.

For multi-paper decks, the talk title fed into build_title_metadata should
be a concise (<=60 char) synthesis of the bundles + user message, not the
verbose user prompt verbatim. The module soft-fails to a truncated user
message on any LLM error so title-synthesis never blocks deck generation.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from paperhub.agents.title_synthesizer import synthesize_talk_title
from paperhub.models.slide_domain import PaperContextBundle


def _bundle(idx: int, title: str, narrative: str) -> PaperContextBundle:
    return PaperContextBundle(
        paper_id=idx + 1,
        paper_idx=idx,
        title=title,
        authors=[],
        year=2025,
        narrative_summary=narrative,
        key_figures=[],
        key_equations=[],
        section_excerpts=[],
        paper_newcommands=[],
    )


@pytest.mark.asyncio
async def test_synthesize_returns_llm_title() -> None:
    llm = AsyncMock()
    llm.return_value = {
        "choices": [{"message": {"content": "Efficient VLA Models: A Synthesis"}}]
    }
    bundles = [_bundle(0, "Paper A", "Contribution: X")]
    title = await synthesize_talk_title(
        bundles=bundles,
        user_message="long user message",
        response_language="English",
        model="stub",
        llm_acompletion=llm,
    )
    assert title == "Efficient VLA Models: A Synthesis"


@pytest.mark.asyncio
async def test_synthesize_caps_title_at_60_chars() -> None:
    llm = AsyncMock()
    long_title = (
        "A very very very very very very very very very long talk title "
        "that exceeds sixty characters"
    )
    llm.return_value = {"choices": [{"message": {"content": long_title}}]}
    bundles = [_bundle(0, "P", "X")]
    title = await synthesize_talk_title(
        bundles=bundles,
        user_message="msg",
        response_language="en",
        model="stub",
        llm_acompletion=llm,
    )
    assert len(title) <= 60


@pytest.mark.asyncio
async def test_synthesize_strips_quotes() -> None:
    llm = AsyncMock()
    llm.return_value = {"choices": [{"message": {"content": '"Wrapped In Quotes"'}}]}
    bundles = [_bundle(0, "P", "X")]
    title = await synthesize_talk_title(
        bundles=bundles,
        user_message="m",
        response_language="en",
        model="stub",
        llm_acompletion=llm,
    )
    assert title == "Wrapped In Quotes"


@pytest.mark.asyncio
async def test_synthesize_falls_back_to_user_message_on_llm_error() -> None:
    """If the LLM raises, return a graceful fallback (user message truncated)."""

    async def boom(**kw: Any) -> Any:
        raise RuntimeError("LLM down")

    bundles = [_bundle(0, "P", "X")]
    title = await synthesize_talk_title(
        bundles=bundles,
        user_message=(
            "The original user prompt that's pretty long and explains the talk"
        ),
        response_language="en",
        model="stub",
        llm_acompletion=boom,
    )
    # Falls back to the first 60 chars of user_message
    assert title.startswith("The original user prompt")
    assert len(title) <= 60


@pytest.mark.asyncio
async def test_synthesize_falls_back_to_default_on_empty_message() -> None:
    async def boom(**kw: Any) -> Any:
        raise RuntimeError("LLM down")

    bundles = [_bundle(0, "P", "X")]
    title = await synthesize_talk_title(
        bundles=bundles,
        user_message="",
        response_language="en",
        model="stub",
        llm_acompletion=boom,
    )
    assert title == "Conference Talk"
