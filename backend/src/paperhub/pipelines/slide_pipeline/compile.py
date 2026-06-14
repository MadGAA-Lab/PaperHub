# backend/src/paperhub/pipelines/slide_pipeline/compile.py
"""Beamer compile-with-revise loop.

Skeleton adapted from reference/paper2slides-plus/src/compiler.py @ 88515c4
(MIT); the LLM-revise step is injected as a callback so this module stays
adapter-agnostic (the Report Agent passes a closure over the LlmAdapter).
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from paperhub.pipelines.slide_pipeline.latex_helpers import sanitize_frametitles

_LOG = logging.getLogger(__name__)

ReviseFn = Callable[[str, str], Awaitable[str]]  # (pdflatex_log, current_tex) -> fixed_tex

PDFLATEX = shutil.which("pdflatex") or "pdflatex"

_OVERFULL_VBOX_RE = re.compile(r"Overfull \\vbox")

# A deck that uses any of these MUST be compiled with xelatex (pdflatex cannot
# run them): the Unicode-engine packages xeCJK/fontspec/ctex, or an explicit
# ``% !TeX program = xelatex`` magic comment the LLM emits for CJK decks.
_XELATEX_TRIGGERS = ("xecjk", "fontspec", "ctex", "% !tex program = xelatex")

_XECJK_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{xeCJK\}", re.IGNORECASE)
_FONTSPEC_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{fontspec\}", re.IGNORECASE)
# Default CJK font shipped by the image's fonts-noto-cjk package. Covers
# Simplified + Traditional + Japanese + Korean glyphs (Noto CJK is unified).
_DEFAULT_CJK_FONT = "Noto Serif CJK SC"
# Default Unicode-capable serif main font for non-CJK scripts (Cyrillic,
# Greek, Latin-Extended, etc.). Operator-installable as ``fonts-noto`` /
# ``fonts-noto-extra`` on Debian, ``noto-fonts`` on Arch. When unavailable
# fontspec falls back to Latin Modern Roman which still covers
# Latin-Extended-A (most European accented characters); explicit Cyrillic /
# Greek / Arabic / Hebrew need the Noto family (or the operator's own
# ``additional_tex_macros`` override taking precedence).
_DEFAULT_MAIN_UNICODE_FONT = "Noto Serif"


def _has_overfull_vbox(log: str) -> bool:
    """Return True when the pdflatex log contains an Overfull \\vbox warning."""
    return bool(_OVERFULL_VBOX_RE.search(log))


def select_engine(tex: str) -> str:
    """Pick the LaTeX engine the deck requires.

    Returns the resolved ``xelatex`` path when the source declares a
    Unicode-engine dependency (xeCJK / fontspec / ctex, or an explicit
    ``% !TeX program = xelatex`` magic comment) AND xelatex is actually
    installed; otherwise ``pdflatex``. The xelatex requirement is real — a CJK
    (e.g. Chinese) deck built for xeCJK silently drops every CJK glyph under
    pdflatex — so we honour it instead of hardcoding pdflatex.
    """
    low = tex.lower()
    if any(trigger in low for trigger in _XELATEX_TRIGGERS):
        xelatex = shutil.which("xelatex")
        if xelatex:
            return xelatex
        _LOG.warning(
            "deck requires xelatex (xeCJK/fontspec/ctex) but xelatex is not on "
            "PATH; falling back to pdflatex — CJK/Unicode glyphs may not render"
        )
    return shutil.which("pdflatex") or PDFLATEX


def ensure_cjk_font(tex: str, font: str = _DEFAULT_CJK_FONT) -> str:
    """Inject a default ``\\setCJKmainfont`` when xeCJK is used but unset.

    xeCJK has no built-in default CJK font on Linux TeX Live, so a preamble
    with a bare ``\\usepackage{xeCJK}`` and no ``\\setCJKmainfont`` errors out
    (MiKTeX on Windows masks this with a configured default). The LLM commonly
    emits exactly that, so we add a font that the image provides. No-op when
    xeCJK is absent or a CJK main font is already set.
    """
    match = _XECJK_RE.search(tex)
    if match is None or "\\setCJKmainfont" in tex:
        return tex
    insert = f"\n\\setCJKmainfont{{{font}}}"
    return tex[: match.end()] + insert + tex[match.end() :]


def ensure_main_unicode_font(tex: str, font: str = _DEFAULT_MAIN_UNICODE_FONT) -> str:
    """Inject a default ``\\setmainfont`` when fontspec is loaded but unset.

    The non-CJK companion to :func:`ensure_cjk_font`. When the deck uses
    fontspec (loaded for any non-ASCII script — Cyrillic, Greek, Arabic,
    Hebrew, Latin-Extended, etc.) and no main font is configured, fontspec
    falls back to Latin Modern Roman which covers Latin-Extended-A but NOT
    Cyrillic / Greek / Arabic / Hebrew. Injecting ``\\setmainfont{Noto
    Serif}`` gives those scripts working glyphs on a host that installs
    ``fonts-noto`` (or equivalent). No-op when fontspec is absent or a
    main font is already set (the operator's ``additional_tex_macros``
    override wins by being emitted earlier).
    """
    match = _FONTSPEC_RE.search(tex)
    if match is None or "\\setmainfont" in tex:
        return tex
    insert = f"\n\\setmainfont{{{font}}}"
    return tex[: match.end()] + insert + tex[match.end() :]


@dataclass(frozen=True)
class CompileResult:
    ok: bool
    attempts: int
    tex: str
    log: str
    page_count: int


def _run_latex(engine: str, tex_name: str, workdir: Path) -> subprocess.CompletedProcess[str]:
    # ``-halt-on-error`` is load-bearing for the slide_agent loop: WITHOUT it,
    # a brace/pgfkeys error in a TikZ frame (a "Runaway argument") makes pdflatex
    # scan to EOF hunting the match and spin until the 180 s timeout — blocking
    # the agent's compile_check for minutes on its FIRST compile, so it never
    # gets the error back to fix. ``-halt-on-error`` stops at the first error in
    # ~1-2 s with a clear log line; warnings (overfull boxes) are NOT errors, so
    # a valid deck still compiles. The timeout is now just a backstop for a
    # genuinely slow (but valid) compile.
    cmd = [engine, "-interaction=nonstopmode", "-halt-on-error", tex_name]
    return subprocess.run(  # noqa: S603 — engine resolved via shutil.which, sandboxed workdir
        cmd, cwd=str(workdir), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180,
    )


def _page_count(pdf: Path) -> int:
    try:
        return len(PdfReader(str(pdf)).pages)
    except Exception as exc:  # noqa: BLE001 — page count is best-effort metadata
        _LOG.warning("_page_count failed for %s: %r", pdf, exc)
        return 0


async def compile_with_revise(
    *, tex: str, workdir: Path, tex_name: str, revise: ReviseFn, max_retries: int = 3,
) -> CompileResult:
    # All blocking I/O (pdflatex, file writes, pypdf) is pushed to a worker
    # thread so a multi-second compile never stalls the FastAPI event loop.
    # The async ``revise`` callback stays on the loop (it awaits the LLM).
    await asyncio.to_thread(workdir.mkdir, parents=True, exist_ok=True)
    current = ensure_main_unicode_font(ensure_cjk_font(sanitize_frametitles(tex)))
    last_log = ""
    pdf_path = workdir / Path(tex_name).with_suffix(".pdf").name
    for attempt in range(1, max_retries + 2):
        # Re-derive engine + font each attempt: the revise step rewrites the
        # TeX and could change (or drop) the xeCJK/fontspec/font lines.
        current = ensure_main_unicode_font(ensure_cjk_font(current))
        engine = select_engine(current)
        await asyncio.to_thread((workdir / tex_name).write_text, current, encoding="utf-8")
        if pdf_path.exists():
            await asyncio.to_thread(pdf_path.unlink)
        try:
            proc = await asyncio.to_thread(_run_latex, engine, tex_name, workdir)
            last_log = (proc.stdout or "") + "\n" + (proc.stderr or "")
        except subprocess.TimeoutExpired as exc:
            last_log = f"{engine} timed out: {exc}"
            proc = subprocess.CompletedProcess([engine], 1, "", last_log)
        pdf_produced = proc.returncode == 0 or pdf_path.exists()
        if pdf_produced and not _has_overfull_vbox(last_log):
            pages = await asyncio.to_thread(_page_count, pdf_path)
            return CompileResult(True, attempt, current, last_log, pages)
        if attempt <= max_retries:
            # Either a hard compile error OR a clean-exit-but-Overfull run —
            # either way, ask the LLM to tighten/fix the TeX and retry.
            # Transient-error retry (Gemini/Vertex connection drops, 5xx) is
            # the LLM-client's responsibility — LiteLlmAdapter.stream wraps
            # streaming calls in its own retry-from-start loop and
            # litellm.num_retries is set globally at app lifespan startup
            # (see paperhub.app._lifespan).
            #
            # If revise's own retries STILL exhaust (upstream provider
            # persistently broken for this workload) AND pdflatex already
            # produced a PDF on this attempt, fall back to shipping the
            # cosmetically-imperfect deck rather than losing the work — a
            # PDF on disk plus an Overfull warning is more useful to the
            # user than no deck at all.
            try:
                current = sanitize_frametitles(await revise(last_log[-4000:], current))
            except Exception as exc:
                if pdf_produced:
                    pages = await asyncio.to_thread(_page_count, pdf_path)
                    _LOG.warning(
                        "compile_with_revise: revise() exhausted retries (%s) "
                        "on attempt %d but a PDF was produced; shipping the "
                        "imperfect deck (%d pages) instead of failing.",
                        exc.__class__.__name__, attempt, pages,
                    )
                    return CompileResult(True, attempt, current, last_log, pages)
                raise
        elif pdf_produced:
            # Retries exhausted but a PDF exists (overfull every time).
            # Return ok=True — a degraded deck is better than a lost deck.
            pages = await asyncio.to_thread(_page_count, pdf_path)
            _LOG.warning(
                "compile_with_revise: Overfull \\vbox persists after %d attempts; "
                "emitting degraded PDF (%d pages)",
                max_retries + 1,
                pages,
            )
            return CompileResult(True, max_retries + 1, current, last_log, pages)
    return CompileResult(False, max_retries + 1, current, last_log, 0)
