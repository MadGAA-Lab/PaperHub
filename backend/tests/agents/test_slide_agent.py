"""F4.5 Phase 8.2 — slide_agent tool-call dispatch loop tests."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from paperhub.agents.slide_agent import SlideAgentResult, run_slide_agent
from paperhub.models.slide_domain import (
    CompileCheckResult,
    FigureDimensions,
    FrameOverflowSignal,
    KeyFigureBundle,
    PaperContextBundle,
    UnrenderedMathFrame,
)


def _bundle() -> PaperContextBundle:
    return PaperContextBundle(
        paper_id=1,
        paper_idx=0,
        title="t",
        authors=[],
        year=2025,
        narrative_summary="x",
        key_figures=[
            KeyFigureBundle(
                key="p0-fig-001",
                role="overview",
                one_line_interpretation="x",
                dimensions=FigureDimensions(width_px=1000, height_px=1000),
            )
        ],
        key_equations=[],
        section_excerpts=[],
        paper_newcommands=[],
    )


def _tool_call_msg(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{tool_name}",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(args),
                            },
                        }
                    ],
                }
            }
        ]
    }


def _final_msg() -> dict[str, Any]:
    return {"choices": [{"message": {"content": "", "tool_calls": []}}]}


_GOOD_DECK = (
    "\\documentclass{beamer}\n"
    "\\begin{document}\n"
    "\\begin{frame}{A}body\\end{frame}\n"
    "\\end{document}\n"
)


@pytest.mark.asyncio
async def test_happy_path_initial_draft_then_compile_then_done(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, fake_tracer: Any
) -> None:
    """Agent calls initial_draft → compile_check (ok=True) → done() → returns."""
    bundles = [_bundle()]
    workdir = tmp_path / "slides"
    workdir.mkdir()

    llm = AsyncMock()
    llm.side_effect = [
        _tool_call_msg("initial_draft", {"deck_tex": _GOOD_DECK}),
        _tool_call_msg("compile_check", {}),
        _tool_call_msg("done", {}),
    ]

    async def fake_compile_check(**kw: Any) -> CompileCheckResult:
        return CompileCheckResult(
            ok=True,
            page_count=1,
            compile_errors=[],
            frame_overflow=[],
            unrendered_math_frames=[],
        )

    monkeypatch.setattr(
        "paperhub.agents.slide_agent.run_compile_check", fake_compile_check
    )

    result = await run_slide_agent(
        bundles=bundles,
        task_description="Generate slides",
        response_language="English",
        resolved_preamble=r"\documentclass{beamer}",
        workdir=workdir,
        existing_deck_tex=None,
        figure_inventory={},
        memory_context="",
        tracer=fake_tracer,
        model="stub",
        llm_acompletion=llm,
    )
    assert isinstance(result, SlideAgentResult)
    assert result.deck_tex == _GOOD_DECK
    assert result.satisfied is True
    assert result.tool_calls_used == 3


@pytest.mark.asyncio
async def test_done_rejected_when_unrendered_math_frames_present(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, fake_tracer: Any
) -> None:
    """compile_check returns unrendered_math; done() is rejected; agent must
    keep going (here it gives up by emitting a no-tool-calls msg → returns
    satisfied=False)."""
    bundles = [_bundle()]
    workdir = tmp_path / "slides"
    workdir.mkdir()

    llm = AsyncMock()
    llm.side_effect = [
        _tool_call_msg("initial_draft", {"deck_tex": _GOOD_DECK}),
        _tool_call_msg("compile_check", {}),
        _tool_call_msg("done", {}),  # rejected
        _final_msg(),  # agent gives up
    ]

    async def fake_compile_check(**kw: Any) -> CompileCheckResult:
        return CompileCheckResult(
            ok=False,
            page_count=1,
            compile_errors=[],
            frame_overflow=[],
            unrendered_math_frames=[
                UnrenderedMathFrame(
                    frame_index=0,
                    frame_title="X",
                    matched_equation_role="r",
                    matched_equation_latex=r"\Phi = 1",
                    paper_idx=0,
                    recommendation="...",
                )
            ],
        )

    monkeypatch.setattr(
        "paperhub.agents.slide_agent.run_compile_check", fake_compile_check
    )

    result = await run_slide_agent(
        bundles=bundles,
        task_description="x",
        response_language="en",
        resolved_preamble=r"\documentclass{beamer}",
        workdir=workdir,
        existing_deck_tex=None,
        figure_inventory={},
        memory_context="",
        tracer=fake_tracer,
        model="stub",
        llm_acompletion=llm,
    )
    assert result.satisfied is False
    assert result.last_compile_check is not None
    assert len(result.last_compile_check.unrendered_math_frames) == 1


@pytest.mark.asyncio
async def test_replace_frame_then_done_resolves_math_violation(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, fake_tracer: Any
) -> None:
    """Realistic remediation: initial_draft → compile (math missing) →
    replace_frame → compile (clean) → done() (accepted)."""
    bundles = [_bundle()]
    workdir = tmp_path / "slides"
    workdir.mkdir()

    llm = AsyncMock()
    llm.side_effect = [
        _tool_call_msg("initial_draft", {"deck_tex": _GOOD_DECK}),
        _tool_call_msg("compile_check", {}),
        _tool_call_msg(
            "replace_frame",
            {
                "frame_index": 0,
                "new_frame_tex": r"\begin{frame}{A}\[ \Phi = 1 \]\end{frame}",
            },
        ),
        _tool_call_msg("compile_check", {}),
        _tool_call_msg("done", {}),
    ]

    call_count = {"n": 0}

    async def fake_compile_check(**kw: Any) -> CompileCheckResult:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return CompileCheckResult(
                ok=False,
                page_count=1,
                compile_errors=[],
                frame_overflow=[],
                unrendered_math_frames=[
                    UnrenderedMathFrame(
                        frame_index=0,
                        frame_title="A",
                        matched_equation_role="r",
                        matched_equation_latex=r"\Phi=1",
                        paper_idx=0,
                        recommendation="x",
                    )
                ],
            )
        return CompileCheckResult(
            ok=True,
            page_count=1,
            compile_errors=[],
            frame_overflow=[],
            unrendered_math_frames=[],
        )

    monkeypatch.setattr(
        "paperhub.agents.slide_agent.run_compile_check", fake_compile_check
    )

    result = await run_slide_agent(
        bundles=bundles,
        task_description="x",
        response_language="en",
        resolved_preamble=r"\documentclass{beamer}",
        workdir=workdir,
        existing_deck_tex=None,
        figure_inventory={},
        memory_context="",
        tracer=fake_tracer,
        model="stub",
        llm_acompletion=llm,
    )
    assert result.satisfied is True
    assert "\\Phi = 1" in result.deck_tex


@pytest.mark.asyncio
async def test_tool_call_budget_exhaustion_ships_imperfect(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, fake_tracer: Any
) -> None:
    """If the agent burns through the tool-call budget without done(), ship
    whatever deck state we have."""
    bundles = [_bundle()]
    workdir = tmp_path / "slides"
    workdir.mkdir()

    overflow_signal = FrameOverflowSignal(
        frame_index=0,
        frame_title="A",
        page_number=1,
        matched_layout="text_only",
        body_token_count=300,
        text_budget_tokens=100,
        overage_tokens=200,
        figure_footprint_cm2=0,
        layout_aspect_mismatch=False,
        exceeds_canvas_budget=True,
        pdflatex_overfull_pt=0.0,
        recommendation="tighten",
        split_hint="no_hint",
    )

    # initial_draft once, then a long parade of compile_check calls.
    msgs = [_tool_call_msg("initial_draft", {"deck_tex": _GOOD_DECK})]
    msgs.extend([_tool_call_msg("compile_check", {})] * 20)
    llm = AsyncMock()
    llm.side_effect = msgs

    async def fake_compile_check(**kw: Any) -> CompileCheckResult:
        return CompileCheckResult(
            ok=True,
            page_count=1,
            compile_errors=[],
            frame_overflow=[overflow_signal],
            unrendered_math_frames=[],
        )

    monkeypatch.setattr(
        "paperhub.agents.slide_agent.run_compile_check", fake_compile_check
    )

    result = await run_slide_agent(
        bundles=bundles,
        task_description="x",
        response_language="en",
        resolved_preamble=r"\documentclass{beamer}",
        workdir=workdir,
        existing_deck_tex=None,
        figure_inventory={},
        memory_context="",
        tracer=fake_tracer,
        model="stub",
        llm_acompletion=llm,
        max_tool_calls=8,
    )
    # Imperfect-deck-ship at budget exhaustion (frame_overflow is advisory).
    assert result.satisfied is False
    assert result.deck_tex == _GOOD_DECK
    assert result.tool_calls_used == 8
