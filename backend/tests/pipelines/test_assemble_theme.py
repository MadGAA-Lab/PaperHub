"""F4.4 T7 — default preamble switched to the Final_Report gold methodology.

The Round-1 architecture lifted the contract dimensions (figure-only-frame,
equation + notation_explanation, named patterns, ADDITIONAL.tex plumbing)
but every output still rendered under ``\\usetheme{metropolis}``. T7 makes
the Berlin/dolphin/professionalfonts/14pt/16:9 + custom-footline + accent
colors stack the DEFAULT (``slide_theme="gold"``), with the legacy minimal
preamble preserved under ``slide_theme="metropolis"`` for backward compat.

The tests:

- ``test_assemble_default_theme_is_gold`` — asserts the gold preamble
  structural elements (documentclass, theme/colortheme/fonttheme, accent
  colour defs, footline override) are present.
- ``test_assemble_metropolis_theme_for_backward_compat`` — asserts the
  legacy minimal preamble (``\\documentclass{beamer}`` +
  ``\\usetheme{metropolis}``) is preserved verbatim.
- ``test_assemble_unknown_theme_falls_back_to_gold`` — defensive: a typo'd
  env-var must not silently produce an unrelated deck.
- ``test_assemble_preserves_graphicspath_and_newcommands_block_in_both_themes``
  — figure-path injection + paper_newcommands block survive both themes.
- ``test_assemble_preserves_cjk_macros_in_both_themes`` — PaperHub's CJK
  path is the LLM-emitted ``xeCJK`` magic comment + the
  ``ensure_cjk_font`` helper at compile time, NOT a CJKutf8/bsmi wrap in
  the assembler. So the equivalent thing to preserve here is that
  user-supplied ``additional_tex_macros`` (where a deck-level CJK setup
  would land) are emitted verbatim regardless of theme.

F4.4 T7 hotfix² broadens the detection from CJK-only to any non-ASCII
codepoint — Cyrillic, Greek, Arabic, Hebrew, Latin-Extended, etc. all
need xelatex + fontspec to render. CJK additionally needs xeCJK. The
extra ``test_assemble_gold_preamble_uses_unicode_engine_on_*`` tests
cover this.
"""
from __future__ import annotations

import pytest

from paperhub.pipelines.slide_pipeline.assemble import (
    AssembleInput,
    assemble_deck,
)


def _input(theme: str, **overrides):  # type: ignore[no-untyped-def]
    base = dict(
        title="Attention Is All You Need",
        theme=theme,
        additional_tex_macros=[],
        cache_source_dirs=["/ws/cache/source"],
        frames=["\\begin{frame}{Intro}body\\end{frame}"],
        author="Vaswani et al.",
        date="2017",
        subtitle="",
    )
    base.update(overrides)
    return AssembleInput(**base)


# ───────────────────── default == gold ─────────────────────────────


def test_assemble_default_theme_is_gold() -> None:
    """A deck assembled with ``theme="gold"`` carries the Final_Report
    preamble's load-bearing structural elements."""
    tex = assemble_deck(_input("gold"))

    # 14pt + 16:9 documentclass — the gold uses both.
    assert "\\documentclass[aspectratio=169,14pt]{beamer}" in tex
    # Theme / colortheme / fonttheme stack.
    assert "\\usetheme{Berlin}" in tex
    assert "\\usecolortheme{dolphin}" in tex
    assert "\\usefonttheme{professionalfonts}" in tex
    # Accent colours.
    assert "\\definecolor{accent}{RGB}{0,90,160}" in tex
    assert "\\definecolor{accent2}{RGB}{200,60,60}" in tex
    assert "\\definecolor{lightgray}{RGB}{240,240,240}" in tex
    # Block colours + navigation suppress + margins.
    assert "\\setbeamercolor{block title}{bg=accent,fg=white}" in tex
    assert "\\setbeamercolor{block body}{bg=lightgray,fg=black}" in tex
    assert "\\setbeamertemplate{navigation symbols}{}" in tex
    assert "\\setbeamersize{text margin left=0.6cm, text margin right=0.6cm}" in tex
    # Custom footline with page-N/total.
    assert "\\setbeamertemplate{footline}{" in tex
    assert "\\insertshorttitle" in tex
    assert "\\insertframenumber{} / \\inserttotalframenumber" in tex
    # Required math/figure packages.
    assert "\\usepackage{booktabs}" in tex
    assert "\\usepackage{mathtools,amssymb}" in tex
    assert "\\usepackage{tikz}" in tex
    assert "\\usepackage{xcolor}" in tex
    # Metadata still flows through.
    assert "\\title{Attention Is All You Need}" in tex
    assert "\\author{Vaswani et al.}" in tex
    # Metropolis must NOT leak in.
    assert "\\usetheme{metropolis}" not in tex


# ─────────────────── metropolis backward compat ────────────────────


def test_assemble_metropolis_theme_for_backward_compat() -> None:
    """``theme="metropolis"`` keeps the legacy minimal preamble verbatim."""
    tex = assemble_deck(_input("metropolis"))

    assert "\\documentclass{beamer}" in tex
    # The legacy preamble does NOT carry the [aspectratio=169,14pt] options.
    assert "[aspectratio=169,14pt]" not in tex
    assert "\\usetheme{metropolis}" in tex
    # Legacy minimal package set.
    assert "\\usepackage{graphicx}" in tex
    assert "\\usepackage{booktabs}" in tex
    assert "\\usepackage{amsmath,amssymb}" in tex
    # Gold-only stack MUST NOT be present.
    assert "\\usetheme{Berlin}" not in tex
    assert "\\usecolortheme{dolphin}" not in tex
    assert "\\usefonttheme{professionalfonts}" not in tex
    assert "\\definecolor{accent}" not in tex
    assert "\\setbeamertemplate{footline}{" not in tex


# ───────────────── unknown theme → gold fallback ───────────────────


def test_assemble_unknown_theme_falls_back_to_gold() -> None:
    """A typo'd env-var (``PAPERHUB_SLIDE_THEME=goldd``) must NOT silently
    produce metropolis — fall back to the new default."""
    tex = assemble_deck(_input("goldd"))
    assert "\\usetheme{Berlin}" in tex
    assert "\\usetheme{metropolis}" not in tex


def test_assemble_empty_theme_falls_back_to_gold() -> None:
    tex = assemble_deck(_input(""))
    assert "\\usetheme{Berlin}" in tex


# ─────── both themes preserve graphicspath + newcommands block ─────


_NEWCOMMANDS_BLOCK = "\n".join(
    [
        "% BEGIN paperhub:paper_newcommands",
        "\\providecommand{\\R}{\\mathbb{R}}",
        "% END paperhub:paper_newcommands",
    ]
)


@pytest.mark.parametrize("theme", ["gold", "metropolis"])
def test_assemble_preserves_graphicspath_and_newcommands_block_in_both_themes(
    theme: str,
) -> None:
    """Figure-path injection AND the paper_newcommands block must land in
    the right spot under BOTH themes: AFTER the package/theme/colour block,
    BEFORE ``\\title{}``."""
    tex = assemble_deck(
        _input(
            theme,
            cache_source_dirs=[
                "/ws/papers_cache/arxiv/2403.01234/source",
                "/ws/papers_cache/arxiv/2401.05678/source",
            ],
            paper_newcommands_block=_NEWCOMMANDS_BLOCK,
        )
    )
    # graphicspath emitted with forward-slash terminator.
    assert (
        "\\graphicspath{ {/ws/papers_cache/arxiv/2403.01234/source/} "
        "{/ws/papers_cache/arxiv/2401.05678/source/} }"
    ) in tex
    # newcommands block emitted with its markers.
    assert "% BEGIN paperhub:paper_newcommands" in tex
    assert "% END paperhub:paper_newcommands" in tex
    assert "\\providecommand{\\R}{\\mathbb{R}}" in tex
    # Position: after the LAST \usepackage (theme/colour block), before \title.
    idx_last_usepackage = tex.rfind("\\usepackage")
    idx_block_begin = tex.find("% BEGIN paperhub:paper_newcommands")
    idx_title = tex.find("\\title{")
    idx_begin_document = tex.find("\\begin{document}")
    assert -1 < idx_last_usepackage < idx_block_begin < idx_title < idx_begin_document


# ─────────── both themes preserve user-supplied macros ─────────────


@pytest.mark.parametrize("theme", ["gold", "metropolis"])
def test_assemble_preserves_cjk_macros_in_both_themes(theme: str) -> None:
    """PaperHub's CJK path is the LLM-emitted ``xeCJK`` magic comment +
    ``ensure_cjk_font`` at compile time, not a CJKutf8/bsmi wrap in the
    assembler. The equivalent invariant is: user-supplied
    ``additional_tex_macros`` (where a deck-level CJK setup would land) are
    emitted verbatim regardless of theme."""
    cjk_macros = [
        "% !TeX program = xelatex",
        "\\usepackage{xeCJK}",
        "\\setCJKmainfont{Noto Serif CJK SC}",
    ]
    tex = assemble_deck(_input(theme, additional_tex_macros=cjk_macros))
    for line in cjk_macros:
        assert line in tex
    # Macros land BEFORE \title{} (so they take effect before the title
    # frame renders).
    idx_first_macro = tex.find(cjk_macros[0])
    idx_title = tex.find("\\title{")
    assert -1 < idx_first_macro < idx_title


# ─────── F4.4 T7 hotfix² — deck-content-aware Unicode (broader than CJK) ───────


def test_assemble_gold_preamble_skips_unicode_engine_on_ascii() -> None:
    """Pure-ASCII deck must NOT pull in fontspec / xeCJK / xelatex — keeping
    the pdflatex compile path and its compile speed."""
    tex = assemble_deck(_input("gold"))  # subtitle="" + ASCII frames
    assert "\\usepackage{xeCJK}" not in tex
    assert "\\usepackage{fontspec}" not in tex
    assert "% !TeX program = xelatex" not in tex


def test_assemble_gold_preamble_uses_unicode_engine_on_cyrillic() -> None:
    """A Cyrillic-containing frame trips xelatex + fontspec (NOT xeCJK —
    Cyrillic is not CJK). ``\\setmainfont`` is intentionally not emitted
    here — ``compile.ensure_main_unicode_font`` owns the default font name."""
    tex = assemble_deck(
        _input("gold", frames=["\\begin{frame}{Intro}Привет мир\\end{frame}"])
    )
    assert tex.splitlines()[0] == "% !TeX program = xelatex"
    assert "\\usepackage{fontspec}" in tex
    assert "\\usepackage{xeCJK}" not in tex
    # compile.ensure_main_unicode_font injects \setmainfont at compile time.
    assert "\\setmainfont" not in tex
    # fontspec lands AFTER textcomp and BEFORE \title{} so it takes effect
    # before any frame body renders.
    idx_textcomp = tex.find("\\usepackage{textcomp}")
    idx_fontspec = tex.find("\\usepackage{fontspec}")
    idx_title = tex.find("\\title{")
    assert -1 < idx_textcomp < idx_fontspec < idx_title


def test_assemble_gold_preamble_uses_unicode_engine_on_greek() -> None:
    """Greek text (e.g. Γεια σου) trips xelatex + fontspec, NOT xeCJK."""
    tex = assemble_deck(
        _input("gold", frames=["\\begin{frame}{Intro}Γεια σου\\end{frame}"])
    )
    assert tex.splitlines()[0] == "% !TeX program = xelatex"
    assert "\\usepackage{fontspec}" in tex
    assert "\\usepackage{xeCJK}" not in tex


def test_assemble_gold_preamble_uses_unicode_engine_on_latin_extended() -> None:
    """European accented characters (Latin-Extended-A like ``café déjà vu``)
    trip xelatex + fontspec. pdflatex with T1 fontenc CAN technically handle
    these via input-encoding tricks but xelatex+fontspec is the robust
    universal path that doesn't depend on inputenc + the specific accent set."""
    tex = assemble_deck(
        _input("gold", frames=["\\begin{frame}{Intro}café déjà vu\\end{frame}"])
    )
    assert tex.splitlines()[0] == "% !TeX program = xelatex"
    assert "\\usepackage{fontspec}" in tex
    assert "\\usepackage{xeCJK}" not in tex


def test_assemble_gold_preamble_uses_unicode_engine_and_xecjk_on_cjk() -> None:
    """A CJK-containing frame trips xelatex + fontspec + xeCJK.
    ``\\setCJKmainfont`` / ``\\setmainfont`` are intentionally NOT emitted
    here — ``compile.ensure_cjk_font`` / ``compile.ensure_main_unicode_font``
    own the default font names so they track the single-place constants."""
    tex = assemble_deck(
        _input("gold", frames=["\\begin{frame}\\frametitle{核心文獻}body\\end{frame}"])
    )
    # Magic comment MUST be line 1 of the file so compile.py picks it up
    # before any other directive.
    assert tex.splitlines()[0] == "% !TeX program = xelatex"
    assert "\\usepackage{fontspec}" in tex
    assert "\\usepackage{xeCJK}" in tex
    assert "\\setCJKmainfont" not in tex
    assert "\\setmainfont" not in tex
    # Ordering: textcomp → fontspec → xeCJK → \title{}, so the Unicode
    # engine + Latin main-font setup precedes the CJK setup which precedes
    # the title frame.
    idx_textcomp = tex.find("\\usepackage{textcomp}")
    idx_fontspec = tex.find("\\usepackage{fontspec}")
    idx_xecjk = tex.find("\\usepackage{xeCJK}")
    idx_title = tex.find("\\title{")
    assert -1 < idx_textcomp < idx_fontspec < idx_xecjk < idx_title


def test_assemble_gold_preamble_uses_unicode_engine_when_cjk_in_subtitle() -> None:
    """The subtitle-only CJK path — frames are ASCII but
    ``\\subtitle{<Chinese>}`` is set — still trips fontspec + xeCJK."""
    tex = assemble_deck(
        _input(
            "gold",
            frames=["\\begin{frame}{Intro}ascii body\\end{frame}"],
            subtitle="核心文獻概述",
        )
    )
    assert tex.splitlines()[0] == "% !TeX program = xelatex"
    assert "\\usepackage{fontspec}" in tex
    assert "\\usepackage{xeCJK}" in tex
    assert "\\subtitle{核心文獻概述}" in tex


def test_assemble_gold_preamble_uses_unicode_engine_when_cjk_in_title() -> None:
    """Defensive: a CJK title also trips the switch (title flows into the
    titlepage frame, which would otherwise render with empty boxes)."""
    tex = assemble_deck(_input("gold", title="注意力即是一切"))
    assert tex.splitlines()[0] == "% !TeX program = xelatex"
    assert "\\usepackage{fontspec}" in tex
    assert "\\usepackage{xeCJK}" in tex


def test_assemble_gold_preamble_uses_unicode_engine_when_cjk_in_author() -> None:
    """Defensive: a CJK author name (e.g. 王小明) also trips the switch."""
    tex = assemble_deck(_input("gold", author="王小明"))
    assert tex.splitlines()[0] == "% !TeX program = xelatex"
    assert "\\usepackage{fontspec}" in tex
    assert "\\usepackage{xeCJK}" in tex


def test_assemble_metropolis_preamble_uses_unicode_engine_on_cyrillic() -> None:
    """Metropolis-theme parity: Cyrillic text trips xelatex + fontspec
    under the legacy minimal preamble too, no xeCJK."""
    tex = assemble_deck(
        _input("metropolis", frames=["\\begin{frame}{Intro}Привет мир\\end{frame}"])
    )
    assert tex.splitlines()[0] == "% !TeX program = xelatex"
    assert "\\usepackage{fontspec}" in tex
    assert "\\usepackage{xeCJK}" not in tex
    # The metropolis stack itself stays intact.
    assert "\\usetheme{metropolis}" in tex


def test_assemble_metropolis_theme_also_handles_cjk() -> None:
    """The Unicode switch is theme-INdependent: a Chinese deck under the
    legacy metropolis preamble must also xelatex-compile with fontspec +
    xeCJK, not silently emit a glyph-less PDF."""
    tex = assemble_deck(
        _input(
            "metropolis", frames=["\\begin{frame}\\frametitle{核心文獻}body\\end{frame}"]
        )
    )
    assert tex.splitlines()[0] == "% !TeX program = xelatex"
    assert "\\usepackage{fontspec}" in tex
    assert "\\usepackage{xeCJK}" in tex
    # The metropolis stack itself stays intact.
    assert "\\usetheme{metropolis}" in tex


def test_assemble_metropolis_preamble_skips_unicode_engine_on_ascii() -> None:
    """Symmetry: pure-ASCII metropolis decks keep the legacy minimal preamble
    verbatim — no xelatex switch, no fontspec, no xeCJK."""
    tex = assemble_deck(_input("metropolis"))
    assert "\\usepackage{xeCJK}" not in tex
    assert "\\usepackage{fontspec}" not in tex
    assert "% !TeX program = xelatex" not in tex


# ──────────────── F4.4 T7 hotfix — default institute anchor ────────────


@pytest.mark.parametrize("theme", ["gold", "metropolis"])
def test_assemble_emits_default_institute_anchor(theme: str) -> None:
    """The Berlin theme's styled title band shrinks when ``\\institute{}``
    is unset, producing the bare-title-page symptom the user reported.
    Default ``\\institute{\\normalsize PaperHub}`` keeps the band anchored.
    """
    tex = assemble_deck(_input(theme))
    assert "\\institute{\\normalsize PaperHub}" in tex
    # Default institute lands in the preamble (before \begin{document}).
    idx_institute = tex.find("\\institute{")
    idx_begin_document = tex.find("\\begin{document}")
    assert -1 < idx_institute < idx_begin_document
