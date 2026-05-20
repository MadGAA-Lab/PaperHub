"""LLM-based PDF title extraction fallback.

When ``doc.metadata['title']`` is empty AND the page-1 largest-font heuristic
in ``extract.py`` also returns empty (the typical InDesign / Word publisher
PDF where the metadata block was stripped AND the title doesn't reliably win
the largest-font race against journal banners / running heads), this module
hands page-1 plain text to a small-tier LLM and asks it to extract just the
title. Cheaper and more robust than hand-rolled font-size + position
heuristics because the model can use semantic signals (academic-paper shape,
title-before-authors-before-abstract layout) that font sizing alone can't.

Best-effort: any LLM failure (network, schema-validation, quota) returns
the empty string so the caller falls through to the filename-stem fallback.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

from paperhub.llm.adapter import LlmAdapter
from paperhub.pipelines.extract import _sanitise_pdf_title

logger = logging.getLogger(__name__)

# Upper bound on the text we forward to the model. 8000 chars ~= 2000 tokens,
# which is more than enough to cover the title region (top of page 1) and
# cheap insurance against pathological PDFs with massive text on page 1
# (e.g. two-column papers with the full body extracted as one stream).
_PAGE1_TEXT_CLIP = 8000


class PaperTitleResult(BaseModel):
    """Structured output schema for the ``paper_title_extract/v1`` prompt."""

    title: str | None = None


async def llm_extract_title(
    adapter: LlmAdapter,
    model: str,
    page1_text: str,
) -> str:
    """Ask the LLM to extract the title from page-1 text.

    Returns the sanitised title on success, or ``""`` on any of:
      - LLM call raised (network / schema / quota)
      - LLM returned ``title=null`` (no plausible title in text)
      - LLM returned a title that ``_sanitise_pdf_title`` rejects
        (stock placeholders, overlong strings, empty / whitespace-only)

    The caller treats ``""`` as "fall through to the next fallback layer"
    (typically the filename stem). The prompt is single-responsibility:
    title extraction only — authors, abstract, year are handled elsewhere.
    """
    clipped = page1_text[:_PAGE1_TEXT_CLIP]
    try:
        result = await adapter.structured(
            slot="paper_title_extract/v1",
            variables={"page1_text": clipped},
            response_model=PaperTitleResult,
            model=model,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "title_extract: LLM call failed (%s: %s); "
            "falling through to filename-stem fallback",
            type(exc).__name__, exc,
        )
        return ""

    raw_title = result.title
    if raw_title is None:
        return ""
    return _sanitise_pdf_title(raw_title)
