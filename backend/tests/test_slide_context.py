from paperhub.agents.slide_context import build_slide_context, slide_aware_query
from paperhub.db.connection import open_db
from paperhub.db.deck_slides import DeckSlideInput, replace_deck_slides
from paperhub.db.decks import get_deck, upsert_deck
from paperhub.db.migrate import apply_schema


async def _seed_deck(conn, *, page_count: int) -> int:
    await conn.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await conn.commit()
    await upsert_deck(
        conn, session_id=1, run_id=None, tex_path="/x/deck.tex", pdf_path=None,
        speaker_notes={}, plan={}, page_count=page_count,
        contributing_paper_ids=[], status="ok",
    )
    deck = await get_deck(conn, session_id=1)
    return deck.id


async def test_no_deck_returns_none(tmp_path) -> None:
    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        await conn.execute("INSERT INTO chat_sessions DEFAULT VALUES")
        await conn.commit()
        assert await build_slide_context(conn, session_id=1, current_view_page=3) is None


async def test_page_zero_returns_none(tmp_path) -> None:
    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        deck_id = await _seed_deck(conn, page_count=1)
        await replace_deck_slides(conn, deck_id=deck_id, slides=[
            DeckSlideInput(slide_index=0, frame_tex="\\begin{frame}{A}\\end{frame}",
                           page_start=1, page_end=1)])
        assert await build_slide_context(conn, session_id=1, current_view_page=0) is None


async def test_text_frame_yields_title_and_bullets(tmp_path) -> None:
    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        deck_id = await _seed_deck(conn, page_count=2)
        frame = (
            "\\begin{frame}{Coarse-to-fine RVQ}\n"
            "  \\begin{itemize}\n"
            "    \\item Action patchifier partitions sequences.\n"
            "    \\item RVQ stabilizes training.\n"
            "  \\end{itemize}\n\\end{frame}"
        )
        await replace_deck_slides(conn, deck_id=deck_id, slides=[
            DeckSlideInput(slide_index=0, frame_tex=frame, page_start=1, page_end=1),
            DeckSlideInput(slide_index=1, frame_tex="\\begin{frame}{B}\\end{frame}",
                           page_start=2, page_end=2)])
        ctx = await build_slide_context(conn, session_id=1, current_view_page=1)
        assert ctx is not None
        assert "Coarse-to-fine RVQ" in ctx
        assert "Action patchifier partitions sequences" in ctx
        assert "RVQ stabilizes training" in ctx
        assert "Figure" not in ctx


async def test_page_out_of_range_returns_none(tmp_path) -> None:
    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        deck_id = await _seed_deck(conn, page_count=1)
        await replace_deck_slides(conn, deck_id=deck_id, slides=[
            DeckSlideInput(slide_index=0, frame_tex="\\begin{frame}{A}\\end{frame}",
                           page_start=1, page_end=1)])
        assert await build_slide_context(conn, session_id=1, current_view_page=9) is None


async def test_frame_title_extracted_with_option_and_overlay_specs(tmp_path) -> None:
    """Regression: _BEGINFRAME_TITLE_RE must match option/overlay variants."""
    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        deck_id = await _seed_deck(conn, page_count=3)
        await replace_deck_slides(conn, deck_id=deck_id, slides=[
            # [plain] option only
            DeckSlideInput(slide_index=0,
                           frame_tex="\\begin{frame}[plain]{Methodology}\\end{frame}",
                           page_start=1, page_end=1),
            # overlay spec + option
            DeckSlideInput(slide_index=1,
                           frame_tex="\\begin{frame}<2->[fragile]{Implementation}\\end{frame}",
                           page_start=2, page_end=2),
            # option only (different option)
            DeckSlideInput(slide_index=2,
                           frame_tex="\\begin{frame}[t]{Results}\\end{frame}",
                           page_start=3, page_end=3),
        ])
        ctx1 = await build_slide_context(conn, session_id=1, current_view_page=1)
        ctx2 = await build_slide_context(conn, session_id=1, current_view_page=2)
        ctx3 = await build_slide_context(conn, session_id=1, current_view_page=3)
        assert ctx1 is not None and "Methodology" in ctx1
        assert "(untitled slide)" not in (ctx1 or "")
        assert ctx2 is not None and "Implementation" in ctx2
        assert "(untitled slide)" not in (ctx2 or "")
        assert ctx3 is not None and "Results" in ctx3
        assert "(untitled slide)" not in (ctx3 or "")


async def test_figure_frame_resolves_caption(tmp_path, monkeypatch) -> None:
    from paperhub.pipelines.slide_pipeline.figure_inventory import InventoryFigure
    monkeypatch.setattr(
        "paperhub.agents.slide_context.build_inventory",
        lambda papers: [InventoryFigure(
            key="p0-fig-002", caption="Fig. 2. Coarse-to-fine residual VQ.",
            abs_path="/x/p0-fig-002.png", paper_id=7)],
    )
    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        deck_id = await _seed_deck(conn, page_count=1)
        frame = ("\\begin{frame}{FASTerVQ Architecture}\n"
                 "  \\includegraphics[width=\\linewidth]{p0-fig-002}\n\\end{frame}")
        await replace_deck_slides(conn, deck_id=deck_id, slides=[
            DeckSlideInput(slide_index=0, frame_tex=frame, page_start=1, page_end=1)])
        ctx = await build_slide_context(conn, session_id=1, current_view_page=1)
        assert ctx is not None
        assert "Fig. 2. Coarse-to-fine residual VQ." in ctx


def test_slide_aware_query_prepends_context_when_present() -> None:
    state = {"user_message": "explain this", "effective_query": "explain this graph",
             "slide_context": "Active slide (page 5) title: Architecture"}
    q = slide_aware_query(state)  # type: ignore[arg-type]
    assert q.startswith("Active slide (page 5) title: Architecture")
    assert "explain this graph" in q


def test_slide_aware_query_passthrough_when_absent() -> None:
    state = {"user_message": "explain this", "effective_query": "explain this graph"}
    assert slide_aware_query(state) == "explain this graph"  # type: ignore[arg-type]
