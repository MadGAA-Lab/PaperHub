from paperhub.agents.slide_agent import _format_outline_block
from paperhub.models.slide_domain import DeckOutline, OutlineSlide


def test_format_outline_block_none_is_empty() -> None:
    assert _format_outline_block(None) == ""


def test_format_outline_block_lists_slides_in_order() -> None:
    outline = DeckOutline(
        talk_title="VLM Talk", audience_intent="walk the references",
        narrative_arc="problem -> method -> takeaway",
        slides=[
            OutlineSlide(slide_index=0, goal="title page", key_message="",
                         transition_from_prev="", paper_id=None, figure_key=None,
                         grounding_chunk_ids=[]),
            OutlineSlide(slide_index=1, goal="motivate the problem", key_message="VLMs hallucinate",
                         transition_from_prev="building on the taxonomy", paper_id=73,
                         figure_key="p0-fig-001", grounding_chunk_ids=[101]),
        ],
    )
    block = _format_outline_block(outline)
    assert "VLM Talk" in block
    assert "problem -> method -> takeaway" in block
    assert "1." in block and "2." in block
    assert "motivate the problem" in block
    assert "p0-fig-001" in block
    assert "exactly one frame" in block.lower()
    # transition_from_prev is SAY content — must NOT appear on the slide
    assert "transition:" not in block
    # title slide has empty key_message -> no dangling em-dash
    assert "title page — " not in block


def test_format_outline_block_content_form_and_evidence() -> None:
    """Slide with content_form + support_excerpts: both must appear in the block."""
    outline = DeckOutline(
        talk_title="Model Comparison Talk",
        audience_intent="compare two approaches",
        narrative_arc="problem -> methods -> comparison -> conclusion",
        slides=[
            OutlineSlide(
                slide_index=0,
                goal="title page",
                key_message="",
                content_form="title",
                transition_from_prev="",
                paper_id=None,
                figure_key=None,
                grounding_chunk_ids=[],
                support_excerpts=[],
            ),
            OutlineSlide(
                slide_index=1,
                goal="compare methods on benchmark X",
                key_message="Method A outperforms Method B on X",
                content_form="comparison_table",
                transition_from_prev="having motivated the problem",
                paper_id=1,
                figure_key=None,
                grounding_chunk_ids=[42, 43],
                support_excerpts=[
                    "Method A scores 0.81 on X",
                    "Method B scores 0.74",
                ],
            ),
        ],
    )
    block = _format_outline_block(outline)

    # content_form marker must be present for the comparison slide
    assert "[form: comparison_table]" in block

    # evidence excerpts must appear
    assert "Method A scores 0.81 on X" in block
    assert "Method B scores 0.74" in block

    # the evidence section header should indicate writing from evidence
    assert "Evidence:" in block

    # title slide has no evidence -> no spurious Evidence: section for it
    # (check by splitting on slide boundaries)
    slide1_section, slide2_section = block.split("2.", 1)
    assert "Evidence:" not in slide1_section.split("Slides:")[-1]

    # content_form for title slide should still appear
    assert "[form: title]" in block

    # existing invariants still hold
    assert "exactly one frame" in block.lower()
    # transition_from_prev is SAY content — must NOT appear on the slide
    assert "transition:" not in block


def test_format_outline_block_long_excerpt_truncated() -> None:
    """Excerpts longer than ~300 chars are trimmed with an ellipsis."""
    long_text = "x" * 400
    outline = DeckOutline(
        talk_title="T",
        audience_intent="A",
        narrative_arc="arc",
        slides=[
            OutlineSlide(
                slide_index=0,
                goal="results",
                key_message="big numbers",
                content_form="results",
                transition_from_prev="",
                paper_id=1,
                figure_key=None,
                grounding_chunk_ids=[],
                support_excerpts=[long_text],
            ),
        ],
    )
    block = _format_outline_block(outline)
    # full 400-char string must NOT appear verbatim
    assert long_text not in block
    # truncated version (first 300 chars) must appear
    assert long_text[:300] in block
    # ellipsis marker
    assert "..." in block
