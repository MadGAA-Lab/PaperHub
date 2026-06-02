"""F4.5 sl_emit - deterministic finalize stage (3rd and last).

Runs AFTER the slide_agent returns satisfied=True (or budget-exhausted with
deck content). Responsibilities:
  1. Contract #1 enforcement - ``verify_and_fix_graphics`` audits every
     ``\\includegraphics`` key against the inventory; unknown keys become
     ``\\textit{[figure omitted]}``. NEVER prompts the LLM (deterministic).
  2. Persist decks + deck_slides rows (one current deck per session per the
     ``UNIQUE(session_id)`` constraint; ``deck_slides`` rebuilt from the
     post-audit frames).
  3. Snapshot the new (tex, speaker_notes) under
     ``edit_history/version_<ts>.json``.
  4. Update ``decks.current_version_id`` to point at the new snapshot.
  5. The caller (report_graph) emits the ``deck`` SSE event from the
     ``EmitResult``.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import aiosqlite

from paperhub.models.slide_domain import KeyFigureBundle
from paperhub.pipelines.slide_pipeline.beamer_helpers import (
    extract_frames_from_beamer,
)
from paperhub.pipelines.slide_pipeline.figure_inventory import (
    verify_and_fix_graphics,
)

# F4.5: defensive post-process — see ``enforce_figure_paragraph_break``.
_INCLUDEGRAPHICS_RE = re.compile(
    r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{[^}]*\}"
)
# A LaTeX command followed by a braced argument; matches ``\vspace{0.3em}``,
# ``\hspace{1pt}``, ``\vspace*{...}`` etc. Used to skip trailing spacing
# directives between the figure and the next real content.
_SPACING_CMD_RE = re.compile(r"\\[hv]space\*?\s*\{[^}]*\}")
# An environment whose internal layout we should NOT touch — columns place
# children side-by-side by design, ``figure`` floats have their own caption
# discipline.
_LAYOUT_ENV_NAMES = ("column", "columns", "figure", "wrapfigure")


def _is_inside_layout_env(tex: str, pos: int) -> bool:
    """Return True if ``pos`` lies inside an unclosed ``column``/``columns``/
    ``figure``/``wrapfigure`` environment.

    Scans ``tex[:pos]`` and counts ``\\begin{env}`` vs ``\\end{env}`` for each
    layout-aware env. If any of them has more opens than closes at ``pos``,
    we're inside one and must NOT inject a ``\\par``.
    """
    head = tex[:pos]
    for env in _LAYOUT_ENV_NAMES:
        opens = len(re.findall(r"\\begin\{" + re.escape(env) + r"\}", head))
        closes = len(re.findall(r"\\end\{" + re.escape(env) + r"\}", head))
        if opens > closes:
            return True
    return False


def enforce_figure_paragraph_break(tex: str) -> str:
    """Inject ``\\par`` between ``\\includegraphics`` (+ trailing spacing) and
    the next non-whitespace content when the LLM omitted the blank line.

    Why: with ``keepaspectratio`` + height-bound includegraphics, the rendered
    image is narrower than ``\\linewidth``; without a paragraph break LaTeX
    flows the following text to the RIGHT of the image (inline box behavior).
    A blank line / ``\\par`` forces the text BELOW the figure.

    The function is idempotent and conservative:
      - Skips if a blank line / ``\\par`` / ``\\\\`` already follows.
      - Skips if the figure is inside ``\\begin{column}`` / ``\\begin{columns}``
        / ``\\begin{figure}`` / ``\\begin{wrapfigure}`` (those envs own
        their own layout).
      - Skips if the next non-whitespace token is ``\\end{...}`` (no text
        follows — nothing to push down).
    """
    out_parts: list[str] = []
    cursor = 0
    for m in _INCLUDEGRAPHICS_RE.finditer(tex):
        # Find the end of the includegraphics "block" — the figure call
        # itself plus any immediately-following \v/hspace commands and
        # whitespace (including newlines, but NOT a blank line which itself
        # already terminates the block correctly).
        block_end = m.end()
        # Walk past any whitespace + spacing commands following the figure.
        scan = block_end
        while scan < len(tex):
            # Skip horizontal whitespace + a single newline (we want to
            # stop the moment we see a blank line — that's the desired
            # paragraph break).
            ws_match = re.match(r"[ \t]*\n", tex[scan:])
            if ws_match:
                scan += ws_match.end()
            spacing_match = _SPACING_CMD_RE.match(tex[scan:])
            if spacing_match:
                # Consume the spacing command; include any trailing
                # horizontal whitespace before the next newline.
                scan += spacing_match.end()
                tail = re.match(r"[ \t]*", tex[scan:])
                if tail:
                    scan += tail.end()
                continue
            break

        # Now ``scan`` is after the figure + trailing spacing cmds, sitting on
        # whatever comes next (possibly a newline starting a blank line, or
        # the next content token).
        remainder = tex[scan:]

        # 1. If a blank line / explicit \par / \\ already exists between the
        #    figure-spacing block and the next content → nothing to do.
        if (
            re.match(r"\s*\n\s*\n", remainder)
            or re.match(r"\s*\\par\b", remainder)
            or re.match(r"\s*\\\\", remainder)
        ):
            continue

        # 2. Look ahead at the first non-whitespace token. If it's an \end{...}
        #    (frame, column, etc.) → no text follows → no injection.
        nonspace = re.match(r"\s*", remainder)
        next_pos = scan + (nonspace.end() if nonspace else 0)
        if next_pos >= len(tex):
            continue
        if tex[next_pos:].startswith("\\end{"):
            continue

        # 3. Skip when the figure is inside a layout-managing environment.
        if _is_inside_layout_env(tex, m.start()):
            continue

        # 4. Inject \par right before the next content. We emit everything up
        #    to ``scan`` verbatim, then ``\par\n`` plus the indentation of the
        #    next line, then continue.
        out_parts.append(tex[cursor:scan])
        # Compute indent of the next non-empty line so the injected \par
        # blends with surrounding style.
        line_match = re.match(r"([ \t]*)\S", remainder)
        indent = line_match.group(1) if line_match else ""
        # Strip any leading whitespace-only newlines from ``remainder`` so we
        # don't double-pad.
        leading_ws = re.match(r"[ \t]*\n", remainder)
        if leading_ws:
            # Preserve a single newline before the \par for readability.
            out_parts.append("\n")
            cursor = scan + leading_ws.end()
        else:
            cursor = scan
        out_parts.append(f"{indent}\\par\n")

    out_parts.append(tex[cursor:])
    return "".join(out_parts)


@dataclass(frozen=True)
class EmitResult:
    deck_id: int
    deck_tex: str  # post-audit (may differ from input on unknown-key replacements)
    page_count: int
    current_version_id: str
    figure_audit_replacements: int  # how many \includegraphics were replaced


def _frame_spans(deck_tex: str) -> list[tuple[str, int, int]]:
    """Return ``[(frame_tex, page_start, page_end), ...]`` in source order.

    ``extract_frames_from_beamer`` already duplicates each frame across its
    overlay pages (page numbers align with the rendered PDF), so collapsing
    by frame body gives ``(content, first_page, last_page)`` per logical
    frame.
    """
    raw = extract_frames_from_beamer(deck_tex)
    if not raw:
        return []
    spans: list[tuple[str, int, int]] = []
    cur_content = raw[0][1]
    cur_start = raw[0][0]
    cur_end = raw[0][0]
    for page_num, content, _s, _e in raw[1:]:
        if content == cur_content and page_num == cur_end + 1:
            cur_end = page_num
            continue
        spans.append((cur_content, cur_start, cur_end))
        cur_content = content
        cur_start = page_num
        cur_end = page_num
    spans.append((cur_content, cur_start, cur_end))
    return spans


async def run_sl_emit(
    *,
    session_id: int,
    run_id: int,
    deck_tex: str,
    workdir: Path,
    page_count: int,
    status: str,  # 'ok' | 'error'
    contributing_paper_ids: list[int],
    figure_inventory: dict[str, KeyFigureBundle],
    conn: aiosqlite.Connection,
    speaker_notes: dict[int, str] | None = None,  # opt-in NOTES path
) -> EmitResult:
    # 1. Contract #1: figure-key audit.
    inventory_keys: set[str] = set(figure_inventory.keys())
    audited_tex, rejected = verify_and_fix_graphics(
        deck_tex, allowed_keys=inventory_keys
    )
    n_replacements = len(rejected)
    # F4.5: defensive — inject \par after \includegraphics+\vspace if the LLM
    # omitted the paragraph break (observed on Chinese decks in real-API gate).
    audited_tex = enforce_figure_paragraph_break(audited_tex)

    # 2. + 3. Filesystem work off the event loop (write audited deck.tex,
    # write the version snapshot under edit_history/).
    deck_path = workdir / "deck.tex"
    pdf_path = workdir / "deck.pdf"
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    version_id = f"version_{ts}"
    snapshot = {
        "tex_content": audited_tex,
        "speaker_notes": {str(k): v for k, v in (speaker_notes or {}).items()},
        "description": "F4.5 sl_emit snapshot",
        "timestamp": ts,
    }

    def _persist_files() -> bool:
        workdir.mkdir(parents=True, exist_ok=True)
        deck_path.write_text(audited_tex, encoding="utf-8")
        edit_history = workdir / "edit_history"
        edit_history.mkdir(exist_ok=True)
        (edit_history / f"{version_id}.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return pdf_path.exists()

    pdf_exists = await asyncio.to_thread(_persist_files)

    # 4. Upsert the decks row.
    speaker_notes_json = (
        json.dumps(
            {str(k): v for k, v in (speaker_notes or {}).items()},
            ensure_ascii=False,
        )
        if speaker_notes
        else None
    )

    await conn.execute(
        """
        INSERT INTO decks (
            session_id, run_id, tex_path, pdf_path, speaker_notes_json,
            plan_json, page_count, current_version_id,
            contributing_paper_ids_json, status, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, datetime('now'), datetime('now')
        )
        ON CONFLICT(session_id) DO UPDATE SET
            run_id = excluded.run_id,
            tex_path = excluded.tex_path,
            pdf_path = excluded.pdf_path,
            speaker_notes_json = excluded.speaker_notes_json,
            page_count = excluded.page_count,
            current_version_id = excluded.current_version_id,
            contributing_paper_ids_json = excluded.contributing_paper_ids_json,
            status = excluded.status,
            updated_at = datetime('now')
        """,
        (
            session_id,
            run_id,
            str(deck_path),
            str(pdf_path) if pdf_exists else None,
            speaker_notes_json,
            page_count,
            version_id,
            json.dumps(contributing_paper_ids),
            status,
        ),
    )

    async with conn.execute(
        "SELECT id FROM decks WHERE session_id = ?", (session_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"sl_emit: decks row not found for session_id={session_id} after upsert"
        )
    deck_id = int(row[0])

    # 5. Rebuild deck_slides rows. Earlier rows (if any) are cleared because
    # frame_count likely changed; notes are reapplied by index from `speaker_notes`.
    await conn.execute("DELETE FROM deck_slides WHERE deck_id = ?", (deck_id,))
    spans = _frame_spans(audited_tex)
    for idx, (frame_tex, page_start, page_end) in enumerate(spans):
        note_text = (speaker_notes or {}).get(idx)
        await conn.execute(
            """
            INSERT INTO deck_slides (
                deck_id, slide_index, frame_tex, note_text, note_language,
                page_start, page_end
            ) VALUES (?, ?, ?, ?, NULL, ?, ?)
            """,
            (deck_id, idx, frame_tex, note_text, page_start, page_end),
        )
    await conn.commit()

    return EmitResult(
        deck_id=deck_id,
        deck_tex=audited_tex,
        page_count=page_count,
        current_version_id=version_id,
        figure_audit_replacements=n_replacements,
    )
