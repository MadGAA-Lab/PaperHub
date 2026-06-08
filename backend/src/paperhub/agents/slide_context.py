"""Active-slide context for slide-aware QA (SRS v2.29).

When the composer's slide chip is attached, ``build_slide_context`` produces a
compact block that anchors paper_qa's section navigation onto the right part of
the paper. Returns ``None`` (→ plain paper_qa, no regression) whenever there is
no deck / no on-screen page / no matching row. ``slide_aware_query`` prepends
the block to the resolved query for both the subagent and the finalizer.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import aiosqlite

from paperhub.agents.state import AgentState, effective_query
from paperhub.db.deck_slides import get_deck_slides
from paperhub.db.decks import get_deck
from paperhub.pipelines.slide_pipeline.figure_inventory import build_inventory

_FRAMETITLE_RE = re.compile(r"\\frametitle\{([^}]*)\}")
_BEGINFRAME_TITLE_RE = re.compile(
    r"\\begin\{frame\}\s*(?:<[^>]*>)?\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}"
)
_GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_ITEM_RE = re.compile(r"\\item\s+(.+)")


def _frame_title(frame_tex: str) -> str:
    m = _FRAMETITLE_RE.search(frame_tex) or _BEGINFRAME_TITLE_RE.search(frame_tex)
    return (m.group(1).strip() if m else "") or "(untitled slide)"


def _strip_latex(s: str) -> str:
    s = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", s)
    s = s.replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", s).strip()


def _frame_bullets(frame_tex: str) -> list[str]:
    return [b for b in (_strip_latex(m.group(1)) for m in _ITEM_RE.finditer(frame_tex)) if b]


def _frame_figure_keys(frame_tex: str) -> list[str]:
    return [Path(m.group(1)).stem for m in _GRAPHICS_RE.finditer(frame_tex)]


async def _enabled_paper_keys(
    conn: aiosqlite.Connection, session_id: int
) -> list[dict[str, object]]:
    # Same ordering (added_at) build_inventory used at deck-build time so the
    # p{idx}-{fig.id} keys reverse correctly.
    async with conn.execute(
        "SELECT pc.id, pc.source_dir_path FROM papers p "
        "JOIN paper_content pc ON pc.id = p.paper_content_id "
        "WHERE p.session_id = ? AND p.enabled = 1 ORDER BY p.added_at",
        (session_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [{"id": r[0], "source_dir": r[1]} for r in rows]


async def build_slide_context(
    conn: aiosqlite.Connection, *, session_id: int, current_view_page: int | None
) -> str | None:
    """Return the active-slide context block, or ``None`` when not applicable.

    Caller gates on the chip's ``slide_attached`` flag BEFORE calling this; this
    function additionally returns None for the no-deck / no-page / no-row cases.
    """
    if current_view_page is None or current_view_page <= 0:
        return None
    deck = await get_deck(conn, session_id=session_id)
    if deck is None:
        return None
    rows = await get_deck_slides(conn, deck_id=deck.id)
    row = next((r for r in rows if r.page_start <= current_view_page <= r.page_end), None)
    if row is None:
        return None

    lines = [
        "The user is currently viewing a slide from a presentation deck "
        "generated from the reference paper(s). Use it to locate and explain "
        "the relevant part of the paper(s) that the slide is based on.",
        f"Active slide (page {current_view_page}) title: {_frame_title(row.frame_tex)}",
    ]
    bullets = _frame_bullets(row.frame_tex)
    if bullets:
        lines.append("Slide bullet points: " + " | ".join(bullets))

    fig_keys = _frame_figure_keys(row.frame_tex)
    if fig_keys:
        papers = await _enabled_paper_keys(conn, session_id)
        inventory = await asyncio.to_thread(build_inventory, papers)
        by_key = {f.key: f.caption for f in inventory}
        captions = [by_key[k] for k in fig_keys if k in by_key]
        if captions:
            lines.append("Figure(s) shown on this slide: " + " || ".join(captions))
    return "\n".join(lines)


def slide_aware_query(state: AgentState) -> str:
    """The QA query: the active-slide context (when present) prepended to the
    router's resolved query, so section navigation targets the right section.
    Falls back to ``effective_query`` when there is no slide context."""
    base = effective_query(state)
    ctx = state.get("slide_context")
    if not ctx:
        return base
    return f"{ctx}\n\nThe user's question: {base}"
