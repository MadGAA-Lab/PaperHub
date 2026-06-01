import pytest

from paperhub.agents.slide_agent_compile import (
    run_compile_check,
    run_density_check,
)
from paperhub.models.slide_domain import (
    FigureDimensions,
    KeyEquationBundle,
    KeyFigureBundle,
    PaperContextBundle,
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
                dimensions=FigureDimensions(width_px=600, height_px=900),
            )
        ],
        key_equations=[
            KeyEquationBundle(
                latex=r"\Phi = \sum a",
                role="visual_token_importance_score",
                notation_legend="",
            )
        ],
        section_excerpts=[],
        paper_newcommands=[],
    )


_GOOD_DECK = r"""\documentclass{beamer}
\begin{document}
\begin{frame}{Intro}
\begin{itemize}\item short\end{itemize}
\end{frame}
\end{document}
"""

_MATH_TOPIC_NO_MATH_DECK = r"""\documentclass{beamer}
\begin{document}
\begin{frame}{Visual Token Importance Scoring}
\begin{itemize}\item we score tokens\end{itemize}
\end{frame}
\end{document}
"""


@pytest.mark.asyncio
async def test_density_check_no_compile_runs_overflow_only(tmp_path):
    bundles = [_bundle()]
    result = await run_density_check(
        deck_tex=_GOOD_DECK,
        bundles=bundles,
        script="en",
    )
    # ok flag isn't meaningful for density_check (no pdflatex) — caller reads
    # frame_overflow + unrendered_math_frames directly.
    assert isinstance(result.frame_overflow, list)
    assert len(result.frame_overflow) == 1
    assert result.compile_errors == []
    assert result.page_count == 0   # density_check never runs pdflatex


@pytest.mark.asyncio
async def test_density_check_flags_math_topic_without_math():
    bundles = [_bundle()]
    result = await run_density_check(
        deck_tex=_MATH_TOPIC_NO_MATH_DECK,
        bundles=bundles,
        script="en",
    )
    assert len(result.unrendered_math_frames) == 1
    assert result.unrendered_math_frames[0].matched_equation_role == "visual_token_importance_score"


@pytest.mark.asyncio
async def test_compile_check_invokes_compile_with_revise_and_aggregates(tmp_path, monkeypatch):
    """compile_check writes deck.tex, runs pdflatex via compile.compile_with_revise,
    then computes overflow + math signals."""
    bundles = [_bundle()]

    async def fake_compile_with_revise(*, tex, workdir, tex_name, revise, max_retries):
        from paperhub.pipelines.slide_pipeline.compile import CompileResult
        return CompileResult(ok=True, attempts=1, tex=tex, log="all good", page_count=1)

    monkeypatch.setattr(
        "paperhub.agents.slide_agent_compile.compile_with_revise", fake_compile_with_revise
    )
    workdir = tmp_path / "slides"
    workdir.mkdir()
    figure_inventory = {b.key_figures[0].key: b.key_figures[0] for b in bundles}
    result = await run_compile_check(
        deck_tex=_GOOD_DECK,
        bundles=bundles,
        figure_inventory=figure_inventory,
        workdir=workdir,
        script="en",
    )
    assert result.ok is True
    assert result.page_count == 1
    assert result.compile_errors == []
    assert len(result.frame_overflow) == 1


@pytest.mark.asyncio
async def test_compile_check_records_compile_errors_when_not_ok(tmp_path, monkeypatch):
    async def fake_compile_with_revise(*, tex, workdir, tex_name, revise, max_retries):
        from paperhub.pipelines.slide_pipeline.compile import CompileResult
        return CompileResult(
            ok=False, attempts=4, tex=tex, log="! Undefined control sequence.\nl.5 \\foo",
            page_count=0,
        )

    monkeypatch.setattr(
        "paperhub.agents.slide_agent_compile.compile_with_revise", fake_compile_with_revise
    )
    result = await run_compile_check(
        deck_tex=_GOOD_DECK,
        bundles=[_bundle()],
        figure_inventory={},
        workdir=tmp_path,
        script="en",
    )
    assert result.ok is False
    assert any("Undefined control sequence" in e for e in result.compile_errors)


@pytest.mark.asyncio
async def test_compile_check_ok_flag_false_when_math_contract_violated(tmp_path, monkeypatch):
    async def fake_compile_with_revise(*, tex, workdir, tex_name, revise, max_retries):
        from paperhub.pipelines.slide_pipeline.compile import CompileResult
        return CompileResult(ok=True, attempts=1, tex=tex, log="", page_count=1)

    monkeypatch.setattr(
        "paperhub.agents.slide_agent_compile.compile_with_revise", fake_compile_with_revise
    )
    result = await run_compile_check(
        deck_tex=_MATH_TOPIC_NO_MATH_DECK,
        bundles=[_bundle()],
        figure_inventory={},
        workdir=tmp_path,
        script="en",
    )
    # compile succeeded BUT math contract violated → ok=False (gates done()).
    assert result.ok is False
    assert len(result.unrendered_math_frames) == 1
    assert result.compile_errors == []
