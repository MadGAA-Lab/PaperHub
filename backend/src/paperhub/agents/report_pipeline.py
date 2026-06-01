"""Traced LLM-calling units for the Report Agent subgraph (Plan F4/F4.5).

The F4 follow-up units (classify_deck_command, author_note, edit_frame,
revise_tex, edit_title_block, edit_preamble_block) are each wrapped in a
Tracer step per the agent-flow observability policy (CLAUDE.md). Every step
records enough state to reconstruct the agent context entirely from the DB
alone. Speaker notes are authored separately by ``author_note`` (the F4 NOTES
flow), NOT generated at deck-create time. The F3/F4 R1 fan-out helpers
(understand_paper, narrate_talk, draft_frame, coherence_pass) were removed in
the F4.5 monolithic-slide-agent cleanup — the slide_agent + gather_context
paths replaced them.
"""
from __future__ import annotations

import re

from paperhub.llm.adapter import LlmAdapter
from paperhub.models.domain import (
    DeckCommand,
    SlideBudget,
    TargetLanguage,
)
from paperhub.tracing.tracer import Tracer

# Strip a leading/trailing markdown code fence (```latex ... ```), tolerating an
# optional language tag on the opening fence.
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$")

# Budget extraction patterns (F4 — SRS v2.21).
_SLIDE_RE = re.compile(r"(\d+)[-\s]*(?:slides?|頁|張|投影片)", re.IGNORECASE)
_MIN_RE = re.compile(r"(\d+)[- ]?(?:min(?:ute)?s?|分鐘|分)", re.IGNORECASE)


def parse_slide_budget(text: str) -> SlideBudget:
    """Extract a slide-count budget from the user's request. Explicit slide
    count wins; else minutes × 0.75; else default 15. Clamped to [8, 30]."""
    count: int | None = None
    m = _SLIDE_RE.search(text)
    if m:
        count = int(m.group(1))
    else:
        mm = _MIN_RE.search(text)
        if mm:
            count = round(int(mm.group(1)) * 0.75)
    if count is None:
        count = 15
    count = max(8, min(30, count))
    return SlideBudget(target_slide_count=count, depth="standard")


# --------------------------------------------------------------------------
# F4 / F4.5 helpers (SRS v2.21+).
#
# The F3/F4 R1 fan-out helpers (understand_paper, narrate_talk, draft_frame,
# coherence_pass) were removed in the F4.5 cleanup — superseded by the
# monolithic slide_agent + gather_context path.
# --------------------------------------------------------------------------
def _strip_code_fences(text: str) -> str:
    """Remove a wrapping markdown code fence from an LLM stream, if present."""
    out = text.strip()
    if out.startswith("```"):
        out = _FENCE_RE.sub("", out)
        out = _FENCE_RE.sub("", out)
    return out.strip()


async def revise_tex(
    *,
    pdflatex_log: str,
    tex: str,
    adapter: LlmAdapter,
    tracer: Tracer,
    model: str,
    **kw: object,
) -> str:
    """Repair the deck's LaTeX in response to a pdflatex log (compile loop).

    Slot ``slides_revise/v1``.  Streams the corrected document, strips any code
    fences.  Traced as ``report:revise``; records the log length + whether the
    output differs from the input.
    """
    async with tracer.step(agent="report", tool="report:revise", model=model) as step:
        step.record_args({"log_len": len(pdflatex_log)})
        tokens: list[str] = []
        async for tok in adapter.stream(
            slot="slides_revise/v1",
            variables={"pdflatex_log": pdflatex_log, "tex": tex},
            model=model,
        ):
            tokens.append(tok)
        revised = _strip_code_fences("".join(tokens))
        if not revised:
            revised = tex
        step.record_result({"log_len": len(pdflatex_log), "changed": revised != tex})
    return revised


# --------------------------------------------------------------------------
# F4: DeckCommand classifier (SRS v2.21).
# --------------------------------------------------------------------------

async def classify_deck_command(
    *, adapter: LlmAdapter, tracer: Tracer, model: str, instruction: str,
    current_view_page: int, deck_outline: str,
) -> DeckCommand:
    """Classify a slides follow-up turn (when a deck already exists) into one
    :class:`DeckCommand` action.  Slot ``slides_deck_command/v1``; traced as
    ``report:deck_command``."""
    async with tracer.step(agent="report", tool="report:deck_command", model=model) as step:
        step.record_args({"instruction": instruction, "current_view_page": current_view_page})
        dec = await adapter.structured(
            slot="slides_deck_command/v1",
            variables={
                "instruction": instruction,
                "current_view_page": current_view_page,
                "deck_outline": deck_outline,
            },
            response_model=DeckCommand,
            model=model,
        )
        step.record_result(dec.model_dump())
    return dec


async def detect_slide_language(
    *, adapter: LlmAdapter, tracer: Tracer, model: str, instruction: str,
) -> str | None:
    """Detect the language the user EXPLICITLY asked the SLIDE CONTENT to be in
    (e.g. "把簡報換成英文" → "English"), independent of the chat-reply language.
    Returns the language name, or ``None`` when none was named (caller falls
    back to ``response_language``). Slot ``slides_target_language/v1``; traced as
    ``report:detect_language``."""
    async with tracer.step(
        agent="report", tool="report:detect_language", model=model
    ) as step:
        step.record_args({"instruction": instruction})
        out = await adapter.structured(
            slot="slides_target_language/v1",
            variables={"instruction": instruction},
            response_model=TargetLanguage,
            model=model,
        )
        step.record_result(out.model_dump())
    return out.language


# --------------------------------------------------------------------------
# F4: Note-author + frame-edit streaming functions (SRS v2.21, Task 8).
# --------------------------------------------------------------------------

async def author_note(
    *,
    adapter: LlmAdapter,
    tracer: Tracer,
    model: str,
    frame_tex: str,
    existing_note: str | None,
    instruction: str | None,
    note_language: str,
) -> str:
    """Write (or rewrite) the SPEAKER NOTE for one Beamer frame.

    When ``existing_note`` is supplied the model translates / rewrites it per
    ``instruction``; otherwise it authors a fresh note from the frame content.
    Slot ``slides_note_author/v1``.  Streams the note token-by-token; traced as
    ``report:note_author``.
    """
    async with tracer.step(agent="report", tool="report:note_author", model=model) as step:
        step.record_args(
            {"note_language": note_language, "has_existing": existing_note is not None}
        )
        toks: list[str] = []
        async for t in adapter.stream(
            slot="slides_note_author/v1",
            variables={
                "frame_tex": frame_tex,
                "existing_note": existing_note or "(none — author fresh)",
                "instruction": instruction or "(none)",
                "note_language": note_language or "the user's language",
            },
            model=model,
        ):
            toks.append(t)
        out = "".join(toks).strip()
        step.record_result({"note": out})
    return out


async def edit_frame(
    *,
    adapter: LlmAdapter,
    tracer: Tracer,
    model: str,
    frame_tex: str,
    instruction: str,
    response_language: str,
) -> str:
    """Rewrite ONE Beamer frame per the user's instruction.

    The model returns only the ``\\begin{frame}...\\end{frame}`` block; any
    stray markdown fences are stripped.  Falls back to the original ``frame_tex``
    if the model returns nothing usable.  Slot ``slides_edit_frame/v1``; traced
    as ``report:edit_frame``.
    """
    async with tracer.step(agent="report", tool="report:edit_frame", model=model) as step:
        step.record_args({"old_frame": frame_tex, "instruction": instruction})
        toks: list[str] = []
        async for t in adapter.stream(
            slot="slides_edit_frame/v1",
            variables={
                "frame_tex": frame_tex,
                "instruction": instruction,
                "response_language": response_language or "the user's language",
            },
            model=model,
        ):
            toks.append(t)
        out = _strip_code_fences("".join(toks))
        step.record_result({"new_frame": out})
    return out or frame_tex


# --------------------------------------------------------------------------
# F4.2: Preamble/title-block editing functions (SRS v2.21, Task B5).
# --------------------------------------------------------------------------

async def _edit_page_block(
    *,
    adapter: LlmAdapter,
    tracer: Tracer,
    model: str,
    slot: str,
    tool: str,
    page_block: str,
    instruction: str,
    response_language: str,
) -> str:
    """Shared implementation for :func:`edit_title_block` and
    :func:`edit_preamble_block`.  Streams an LLM rewrite of the deck's
    page-1 source block (preamble + title frame), strips code fences, and
    traces the step."""
    async with tracer.step(agent="report", tool=tool, model=model) as step:
        step.record_args({"instruction": instruction, "block_len": len(page_block)})
        toks: list[str] = []
        async for t in adapter.stream(
            slot=slot,
            variables={
                "page_block": page_block,
                "instruction": instruction,
                "response_language": response_language or "the user's language",
            },
            model=model,
        ):
            toks.append(t)
        out = _strip_code_fences("".join(toks)).strip()
        result = out or page_block  # fall back to the original on empty output
        step.record_result({"new_block_len": len(result)})
    return result


async def edit_title_block(
    *,
    adapter: LlmAdapter,
    tracer: Tracer,
    model: str,
    page_block: str,
    instruction: str,
    response_language: str,
) -> str:
    """Rewrite the title page's metadata + title-frame layout (F4.2).

    Slot ``slides_edit_title/v1``; traced as ``report:edit_title``.
    """
    return await _edit_page_block(
        adapter=adapter,
        tracer=tracer,
        model=model,
        slot="slides_edit_title/v1",
        tool="report:edit_title",
        page_block=page_block,
        instruction=instruction,
        response_language=response_language,
    )


async def edit_preamble_block(
    *,
    adapter: LlmAdapter,
    tracer: Tracer,
    model: str,
    page_block: str,
    instruction: str,
    response_language: str,
) -> str:
    """Restyle the whole deck via its preamble (theme/colors/fonts/header-footer)
    (F4.2).

    Slot ``slides_edit_preamble/v1``; traced as ``report:edit_preamble``.
    """
    return await _edit_page_block(
        adapter=adapter,
        tracer=tracer,
        model=model,
        slot="slides_edit_preamble/v1",
        tool="report:edit_preamble",
        page_block=page_block,
        instruction=instruction,
        response_language=response_language,
    )
