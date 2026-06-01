import pytest
from pydantic import ValidationError

from paperhub.models.slide_domain import (
    CompileCheckResult,
    FigureDimensions,
    FrameOverflowSignal,
    KeyEquationBundle,
    KeyFigureBundle,
    PaperContextBundle,
    UnrenderedMathFrame,
)


def test_figure_dimensions_aspect_ratio_derives_from_w_over_h():
    dims = FigureDimensions(width_px=1640, height_px=920)
    assert dims.aspect_ratio == pytest.approx(1640 / 920)


def test_key_figure_bundle_extra_forbid():
    with pytest.raises(ValidationError):
        KeyFigureBundle(
            key="p0-fig-001",
            role="overview",
            one_line_interpretation="x",
            dimensions=FigureDimensions(width_px=100, height_px=100),
            unknown_field=1,
        )


def test_paper_context_bundle_minimal():
    bundle = PaperContextBundle(
        paper_id=1,
        paper_idx=0,
        title="Test paper",
        authors=["Doe, J."],
        year=2025,
        narrative_summary="Contribution: foo. Method: bar. Results: baz.",
        key_figures=[
            KeyFigureBundle(
                key="p0-fig-001",
                role="overview",
                one_line_interpretation="A diagram",
                dimensions=FigureDimensions(width_px=1640, height_px=920),
            )
        ],
        key_equations=[
            KeyEquationBundle(
                latex=r"\Phi = \frac{1}{N} \sum x",
                role="importance_score",
                notation_legend="Phi: score; N: count",
            )
        ],
        section_excerpts=[],
        paper_newcommands=[],
    )
    assert bundle.paper_id == 1
    assert len(bundle.key_figures) == 1
    assert bundle.key_figures[0].dimensions.aspect_ratio == pytest.approx(1640 / 920)


def test_frame_overflow_signal_recommendation_enum():
    sig = FrameOverflowSignal(
        frame_index=7,
        frame_title="X",
        page_number=8,
        matched_layout="figure_left_half_portrait",
        body_token_count=187,
        text_budget_tokens=85,
        overage_tokens=102,
        figure_footprint_cm2=39.0,
        layout_aspect_mismatch=False,
        exceeds_canvas_budget=True,
        pdflatex_overfull_pt=23.7,
        recommendation="split_frame",
        split_hint="figure_to_own_frame_then_text",
    )
    assert sig.recommendation == "split_frame"
    with pytest.raises(ValidationError):
        FrameOverflowSignal(
            frame_index=0, frame_title="", page_number=1, matched_layout="x",
            body_token_count=0, text_budget_tokens=0, overage_tokens=0,
            figure_footprint_cm2=0, layout_aspect_mismatch=False,
            exceeds_canvas_budget=False, pdflatex_overfull_pt=0.0,
            recommendation="bogus",
        )


def test_unrendered_math_frame_required_fields():
    f = UnrenderedMathFrame(
        frame_index=3,
        frame_title="Visual Token Importance Scoring",
        matched_equation_role="visual_token_importance_score",
        matched_equation_latex=r"\Phi = \frac{1}{N} \sum",
        paper_idx=0,
        recommendation="replace_frame with equation_centered layout",
    )
    assert f.frame_index == 3


def test_compile_check_result_shape():
    r = CompileCheckResult(
        ok=False,
        page_count=9,
        compile_errors=["Undefined control sequence \\foo"],
        frame_overflow=[],
        unrendered_math_frames=[],
    )
    assert r.ok is False
    assert r.page_count == 9
