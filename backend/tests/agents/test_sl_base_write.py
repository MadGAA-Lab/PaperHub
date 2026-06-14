"""Base Writer (deterministic draft) unit tests.

``run_base_write`` is one generation (no tools): the whole streamed response
IS the deck.tex. It strips a leading/trailing ```latex fence defensively and is
traced as ``report:base_write``.
"""
from __future__ import annotations

from typing import Any

import pytest

from paperhub.agents.sl_base_write import run_base_write
from paperhub.models.slide_domain import (
    DeckOutline,
    FigureDimensions,
    KeyEquationBundle,
    KeyFigureBundle,
    OutlineSlide,
    PaperContextBundle,
    SectionExcerpt,
)
from paperhub.tracing.tracer import Tracer


def _outline() -> DeckOutline:
    return DeckOutline(
        talk_title="T",
        narrative_pattern="single_paper",
        audience_intent="i",
        narrative_arc="a",
        slides=[
            OutlineSlide(
                slide_index=0,
                goal="Title",
                key_message="m",
                content_form="title",
                transition_from_prev="",
                paper_id=None,
                figure_key=None,
                grounding_chunk_ids=[],
            ),
            OutlineSlide(
                slide_index=1,
                goal="Method",
                key_message="how it works",
                content_form="bullets",
                transition_from_prev="",
                paper_id=1,
                figure_key="p0-fig-001",
                grounding_chunk_ids=[],
                support_excerpts=["the encoder uses cross attention"],
            ),
        ],
    )


def _bundle() -> PaperContextBundle:
    return PaperContextBundle(
        paper_id=1,
        paper_idx=0,
        title="t",
        authors=["Alice"],
        year=2025,
        narrative_summary="x",
        key_figures=[
            KeyFigureBundle(
                key="p0-fig-001",
                role="overview",
                one_line_interpretation="overview diagram",
                dimensions=FigureDimensions(width_px=1000, height_px=1000),
            )
        ],
        key_equations=[
            KeyEquationBundle(latex=r"E = mc^2", role="energy", notation_legend="")
        ],
        section_excerpts=[SectionExcerpt(section_name="Method", text="method text")],
        paper_newcommands=[],
    )


async def _make_tracer(migrated_db: Any) -> Tracer:
    await migrated_db.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await migrated_db.execute("INSERT INTO runs (session_id) VALUES (1)")
    await migrated_db.commit()
    async with migrated_db.execute("SELECT last_insert_rowid()") as cur:
        row = await cur.fetchone()
    assert row is not None
    return Tracer(migrated_db, run_id=int(row[0]), branch="")


@pytest.mark.asyncio
async def test_run_base_write_returns_full_deck_and_strips_fence(
    migrated_db: Any,
) -> None:
    """The streamed deck arrives wrapped in a ```latex fence; run_base_write
    strips the fence and returns the bare deck.tex."""

    class _Stub:
        async def stream(self, **kw: Any):  # type: ignore[no-untyped-def]
            for tok in [
                "```latex\n",
                "\\documentclass{beamer}\n",
                "\\begin{document}\\begin{frame}{A}body\\end{frame}\\end{document}\n",
                "```",
            ]:
                yield tok

    tracer = await _make_tracer(migrated_db)
    deck = await run_base_write(
        outline=_outline(),
        bundles=[_bundle()],
        resolved_preamble=r"\documentclass{beamer}",
        response_language="en",
        adapter=_Stub(),
        tracer=tracer,
        model="stub",
    )
    assert deck.strip().startswith("\\documentclass")
    assert "```" not in deck
    assert "\\begin{frame}" in deck


@pytest.mark.asyncio
async def test_run_base_write_passes_expected_variables(migrated_db: Any) -> None:
    """The base writer fills exactly the slot variables the prompt declares —
    so a missing key would crash ``.format`` inside the adapter."""
    captured: dict[str, Any] = {}

    class _Stub:
        async def stream(self, **kw: Any):  # type: ignore[no-untyped-def]
            captured.update(kw)
            for tok in ["\\documentclass{beamer}\n", "\\begin{document}\\end{document}"]:
                yield tok

    tracer = await _make_tracer(migrated_db)
    await run_base_write(
        outline=_outline(),
        bundles=[_bundle()],
        resolved_preamble=r"\documentclass{beamer}",
        response_language="en",
        adapter=_Stub(),
        tracer=tracer,
        model="stub",
        figure_inventory_block="- p0-fig-001: aspect=1.00",
    )
    assert captured["slot"] == "slides_base_write/v1"
    variables = captured["variables"]
    assert set(variables) == {
        "task_description",
        "response_language",
        "resolved_preamble",
        "outline_block",
        "bundles_block",
        "n_bundles",
        "figure_inventory_block",
    }
    assert variables["n_bundles"] == 1
    assert variables["figure_inventory_block"] == "- p0-fig-001: aspect=1.00"


@pytest.mark.asyncio
async def test_run_base_write_records_trace_step(migrated_db: Any) -> None:
    """A ``report:base_write`` step is recorded with deck length + frame count."""

    class _Stub:
        async def stream(self, **kw: Any):  # type: ignore[no-untyped-def]
            yield "\\documentclass{beamer}\\begin{document}"
            yield "\\begin{frame}{A}a\\end{frame}\\begin{frame}{B}b\\end{frame}"
            yield "\\end{document}"

    tracer = await _make_tracer(migrated_db)
    await run_base_write(
        outline=_outline(),
        bundles=[_bundle()],
        resolved_preamble=r"\documentclass{beamer}",
        response_language="en",
        adapter=_Stub(),
        tracer=tracer,
        model="stub",
    )
    async with migrated_db.execute(
        "SELECT tool, result_summary_json FROM tool_calls "
        "WHERE run_id = ? ORDER BY step_index DESC LIMIT 1",
        (tracer.run_id,),
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    tool, result_json = row
    assert tool == "report:base_write"
    import json

    result = json.loads(result_json)
    assert result["n_frames"] == 2
    assert result["deck_len"] > 0
