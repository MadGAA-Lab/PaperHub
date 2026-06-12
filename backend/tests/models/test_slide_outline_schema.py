from paperhub.models.slide_domain import (
    DeckOutline,
    DeckOutlineDraft,
    OutlineSlide,
    OutlineSlideDraft,
)


def test_draft_slide_defaults_are_empty() -> None:
    s = OutlineSlideDraft(goal="g", key_message="k")
    assert s.transition_from_prev == ""
    assert s.paper_id is None
    assert s.figure_key is None
    assert s.grounding_sections == []


def test_draft_outline_holds_slides() -> None:
    d = DeckOutlineDraft(
        talk_title="T",
        audience_intent="walk through the references",
        narrative_arc="problem -> method -> takeaway",
        slides=[OutlineSlideDraft(goal="title", key_message="")],
    )
    assert len(d.slides) == 1


def test_resolved_slide_carries_index_and_grounding() -> None:
    s = OutlineSlide(
        slide_index=2,
        goal="g",
        key_message="k",
        transition_from_prev="bridge",
        paper_id=73,
        figure_key="p0-fig-001",
        grounding_chunk_ids=[85229, 85230],
    )
    assert s.slide_index == 2
    assert s.grounding_chunk_ids == [85229, 85230]


def test_resolved_outline_roundtrips_json() -> None:
    d = DeckOutline(
        talk_title="T",
        audience_intent="ai",
        narrative_arc="arc",
        slides=[
            OutlineSlide(
                slide_index=0, goal="title", key_message="", transition_from_prev="",
                paper_id=None, figure_key=None, grounding_chunk_ids=[],
            )
        ],
    )
    assert DeckOutline.model_validate_json(d.model_dump_json()) == d


def test_outline_has_narrative_pattern_and_slide_evidence() -> None:
    from paperhub.models.slide_domain import DeckOutline, OutlineSlide
    o = DeckOutline(
        talk_title="T", narrative_pattern="comparison", audience_intent="ai",
        narrative_arc="arc",
        slides=[OutlineSlide(
            slide_index=0, goal="g", key_message="concept", content_form="comparison_table",
            transition_from_prev="", paper_id=73, figure_key=None, grounding_chunk_ids=[1],
            support_excerpts=["evidence sentence the drafter writes from"],
        )],
    )
    assert o.narrative_pattern == "comparison"
    assert o.slides[0].content_form == "comparison_table"
    assert o.slides[0].support_excerpts == ["evidence sentence the drafter writes from"]


def test_new_field_defaults_keep_existing_construction_working() -> None:
    # constructing WITHOUT the new fields must still work (defaults) — guards the build
    from paperhub.models.slide_domain import DeckOutline, OutlineSlide
    o = DeckOutline(talk_title="T", audience_intent="a", narrative_arc="b", slides=[
        OutlineSlide(slide_index=0, goal="g", key_message="", transition_from_prev="",
                     paper_id=None, figure_key=None, grounding_chunk_ids=[])])
    assert o.narrative_pattern == "synthesis"
    assert o.slides[0].content_form == "bullets"
    assert o.slides[0].support_excerpts == []


def test_seed_and_outline_result_types() -> None:
    from paperhub.models.slide_domain import DeckOutline, OutlineResult, SeedFigure, SeedPaper
    sp = SeedPaper(paper_id=73, title="A Survey of X", abstract="...",
                   is_survey=True, sections=["Intro", "Taxonomy"],
                   figures=[SeedFigure(key="p0-fig-001", caption="c")])
    assert sp.is_survey and sp.sections == ["Intro", "Taxonomy"]
    res = OutlineResult(outline=DeckOutline(talk_title="T", narrative_pattern="taxonomy",
                        audience_intent="a", narrative_arc="b", slides=[]), rounds_used=2)
    assert res.rounds_used == 2
