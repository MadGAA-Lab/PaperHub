"""Replace one frame body in a full deck source (manual "edit current frame").

The Slides panel's per-frame editor sends back a single edited
``\\begin{frame}…\\end{frame}`` block; this splices it into ``deck.tex`` in
place of the original frame, leaving every other byte — including a preceding
``% cite:`` grounding marker, which sits OUTSIDE the frame body — untouched.

The stored ``deck_slides.frame_tex`` is byte-identical to the frame body in
``deck.tex`` (both produced by ``extract_frames_from_beamer``), so the match is
an exact substring. A frame that appears zero or more-than-once is surfaced as a
``ValueError`` rather than silently mishandled — the caller (the manual-edit
endpoint) returns the error and the user falls back to "Edit all deck".
"""
from __future__ import annotations


def splice_frame(deck_tex: str, old_frame_tex: str, new_frame_tex: str) -> str:
    """Return ``deck_tex`` with the single ``old_frame_tex`` block replaced by
    ``new_frame_tex``.

    Raises
    ------
    ValueError
        If ``old_frame_tex`` does not appear in ``deck_tex`` ("not found"), or
        appears more than once ("ambiguous" — two byte-identical frames, which
        the splice refuses to guess between).
    """
    count = deck_tex.count(old_frame_tex)
    if count == 0:
        raise ValueError("frame not found in deck source")
    if count > 1:
        raise ValueError(
            f"frame is ambiguous (matches {count} locations in the deck source)"
        )
    return deck_tex.replace(old_frame_tex, new_frame_tex, 1)


__all__ = ["splice_frame"]
