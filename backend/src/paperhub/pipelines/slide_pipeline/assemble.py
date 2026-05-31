"""Assemble a Beamer deck from generated section frames (new code).

Writes the preamble (theme + ADDITIONAL.tex), title frame, all section frames,
and a single \\graphicspath spanning every contributing paper's cache source
dir (SRS v2.18 §III-5.3 step 4a). Figures are never copied into the session dir.

F4.4 T7: the default preamble profile is the Final_Report gold methodology
(Berlin / dolphin / professionalfonts / 14pt / 16:9 + accent colors +
custom footline + booktabs/mathtools/tikz). The legacy minimal preamble
(``\\documentclass{beamer}`` + ``\\usetheme{metropolis}``) is preserved
under ``theme="metropolis"`` for parity / debugging. Unknown theme values
fall back to ``"gold"`` so a stray env-var typo cannot silently produce a
deck under an unrelated theme.

F4.4 T7 hotfix²: deck-content-aware Unicode setup (broader than CJK).
Any non-ASCII character in the deck text (frames / title / subtitle /
author) flips the preamble into xelatex + fontspec mode so compile.py's
``select_engine`` switches engines and ``ensure_main_unicode_font``
injects ``\\setmainfont{Noto Serif}`` at compile time — covering
Cyrillic, Greek, Arabic, Hebrew, Latin-Extended (European accented
characters), Devanagari, Thai, Vietnamese, etc. CJK additionally pulls
in ``\\usepackage{xeCJK}`` (``ensure_cjk_font`` injects the CJK main
font at compile time). Pure-ASCII decks keep the pdflatex compile path
(and its compile speed). Applies to BOTH ``gold`` and ``metropolis``
preambles so the policy is theme-independent. The deterministic
detection means the LLM never has to remember to emit the right
``\\usepackage`` lines; ``sl_revise`` stays as a final-line-of-defense
LLM repair for unexpected compile errors after deterministic setup.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Recognised preamble-profile names. Anything else falls back to ``GOLD``.
GOLD = "gold"
METROPOLIS = "metropolis"
_KNOWN_THEMES = frozenset({GOLD, METROPOLIS})


# CJK detection — covers the BMP CJK Unified Ideographs block (U+4E00–U+9FFF,
# the bulk of Simplified/Traditional Chinese + Japanese kanji), the CJK
# Symbols and Punctuation block (U+3000–U+303F, e.g. 「」、・), Hiragana
# (U+3040–U+309F), Katakana (U+30A0–U+30FF), Hangul Syllables
# (U+AC00–U+D7AF), and the Halfwidth/Fullwidth Forms block (U+FF00–U+FFEF,
# fullwidth ASCII like ！？).  This is intentionally broader than just CJK
# Unified Ideographs so a deck whose only "Chinese" content is a CJK
# punctuation mark still trips the xeCJK switch.
_CJK_RANGE_RE = re.compile(
    r"[　-〿぀-ゟ゠-ヿ一-鿿가-힯＀-￯]"
)

# Broader non-ASCII detector — fires on ANY codepoint outside the basic
# ASCII range (Cyrillic, Greek, Arabic, Hebrew, Devanagari, Thai,
# Vietnamese with diacritics, Latin-Extended-A with European accented
# characters, etc.). Pdflatex cannot render any of these; xelatex +
# fontspec can.
_NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")

# Title-band anchor when no ``\institute{}`` is supplied. The Berlin theme's
# styled colored title band shrinks visibly when this slot is empty, which
# users mistake for "the title page style is gone". A small ``PaperHub``
# wordmark keeps the band anchored without overpowering the actual title.
_DEFAULT_INSTITUTE = "\\institute{\\normalsize PaperHub}"


@dataclass(frozen=True)
class UnicodeProfile:
    """Two-axis classification of a deck's visible text.

    ``needs_unicode_engine`` — ANY non-ASCII codepoint present. Trips the
    ``% !TeX program = xelatex`` magic comment + ``\\usepackage{fontspec}``
    so the deck compiles under xelatex with a Unicode-capable main font
    (``compile.ensure_main_unicode_font`` injects ``\\setmainfont{Noto
    Serif}`` at compile time, covering Cyrillic / Greek / Arabic / Hebrew
    / Latin-Extended / etc.).

    ``needs_cjk`` — CJK codepoint present. Additionally pulls in
    ``\\usepackage{xeCJK}`` (``compile.ensure_cjk_font`` injects
    ``\\setCJKmainfont{Noto Serif CJK SC}`` at compile time). Implies
    ``needs_unicode_engine`` — every CJK char is also non-ASCII — but
    callers should not rely on that invariant; check both fields.
    """

    needs_unicode_engine: bool
    needs_cjk: bool


def _unicode_profile(*texts: str) -> UnicodeProfile:
    """Classify the deck's text along the two axes above.

    Single pass over the joined string for each regex so a CJK-only
    ``\\subtitle{}`` with ASCII frames (or vice-versa) still trips the
    right switches.
    """
    blob = "".join(t or "" for t in texts)
    return UnicodeProfile(
        needs_unicode_engine=bool(_NON_ASCII_RE.search(blob)),
        needs_cjk=bool(_CJK_RANGE_RE.search(blob)),
    )


@dataclass
class AssembleInput:
    title: str
    theme: str
    additional_tex_macros: list[str]
    cache_source_dirs: list[str]
    frames: list[str]
    author: str = ""
    date: str = ""
    subtitle: str = ""
    # F4.4 T4: deduplicated paper-defined ``\newcommand`` /
    # ``\renewcommand`` / ``\DeclareMathOperator`` block, already wrapped
    # with the ``% BEGIN/END paperhub:paper_newcommands`` markers by
    # :func:`paperhub.agents._newcommands.build_newcommands_block`.
    # Inserted AFTER any ``ADDITIONAL.tex`` macros and BEFORE ``\title{}``
    # so paper-defined macros are visible everywhere in the deck.
    paper_newcommands_block: str = ""
    # F4.4 T5 review-fix: when True, do NOT prepend the auto-injected
    # ``\begin{frame}[plain]\titlepage\end{frame}`` — the caller has
    # already supplied a title frame in ``frames``. T3's ``title``
    # pattern template emits exactly that frame, and the T5 planner
    # ALWAYS emits a ``title`` PlannedSlide as slide #1, so without this
    # toggle the deck would have TWO leading identical title pages.
    # Default ``False`` preserves the pre-T5 behaviour for callers that
    # do not supply a title frame themselves.
    skip_title_injection: bool = False


def build_additional_block(macros: list[str]) -> str:
    if not macros:
        return ""
    return "\n".join(macros)


def build_graphicspath(cache_source_dirs: list[str]) -> str:
    if not cache_source_dirs:
        return ""
    dirs = " ".join(
        "{" + d.replace("\\", "/").rstrip("/") + "/}" for d in cache_source_dirs
    )
    return f"\\graphicspath{{ {dirs} }}"


def _build_metropolis_preamble_head(profile: UnicodeProfile | None = None) -> list[str]:
    """Legacy minimal preamble — preserved for ``theme="metropolis"`` parity.

    When ``profile.needs_unicode_engine`` is True, prepend the ``% !TeX
    program = xelatex`` magic comment and add ``\\usepackage{fontspec}``
    so compile.py's ``select_engine`` switches to xelatex and
    ``ensure_main_unicode_font`` injects the default Unicode main font at
    compile time. When ``profile.needs_cjk`` is additionally True, append
    ``\\usepackage{xeCJK}`` so ``ensure_cjk_font`` injects the default CJK
    main font at compile time.
    """
    profile = profile or UnicodeProfile(False, False)
    head = [
        "\\documentclass{beamer}",
        "\\usetheme{metropolis}",
        "\\usepackage{graphicx}",
        "\\usepackage{booktabs}",
        "\\usepackage{amsmath,amssymb}",
    ]
    if profile.needs_unicode_engine:
        # fontspec lands right after the math packages so it takes effect
        # before any frame body renders; xeCJK lands after fontspec when
        # CJK is also present.
        head.append("\\usepackage{fontspec}")
        if profile.needs_cjk:
            head.append("\\usepackage{xeCJK}")
        # Magic comment MUST be line 1 — compile.py's _XELATEX_TRIGGERS
        # check is substring-based but a leading magic comment is also the
        # convention TeX editors (and humans) recognise.
        head = ["% !TeX program = xelatex", *head]
    return head


def _build_gold_preamble_head(profile: UnicodeProfile | None = None) -> list[str]:
    """F4.4 T7 default: the Final_Report gold methodology preamble.

    Verbatim port of ``D:/GitHub/Final_Report/slides.tex`` lines 1-35 minus
    the deck-specific watermark (which baked a hardcoded ``nycu.png`` and an
    ID-3-3 footer string). Layout/colors/footline/theme are the gold's;
    figures + title metadata are still filled by the caller as before.

    When ``profile.needs_unicode_engine`` is True, adds ``fontspec`` (after
    textcomp) so non-ASCII glyphs render; when ``profile.needs_cjk`` is
    also True, adds ``xeCJK`` after fontspec.
    """
    profile = profile or UnicodeProfile(False, False)
    head = [
        "\\documentclass[aspectratio=169,14pt]{beamer}",
        "\\usepackage[T1]{fontenc}",
        "\\usepackage{textcomp}",
        *(["\\usepackage{fontspec}"] if profile.needs_unicode_engine else []),
        *(["\\usepackage{xeCJK}"] if profile.needs_cjk else []),
        "\\usepackage{graphicx}",
        "\\usepackage{booktabs}",
        "\\usepackage{mathtools,amssymb}",
        "\\usepackage{amsmath}",
        "\\usepackage{bm}",
        "\\usepackage{xcolor}",
        "\\usepackage{tikz}",
        "",
        "\\usetheme{Berlin}",
        "\\usecolortheme{dolphin}",
        "\\usefonttheme{professionalfonts}",
        "",
        "\\definecolor{accent}{RGB}{0,90,160}",
        "\\definecolor{accent2}{RGB}{200,60,60}",
        "\\definecolor{lightgray}{RGB}{240,240,240}",
        "",
        "\\setbeamercolor{block title}{bg=accent,fg=white}",
        "\\setbeamercolor{block body}{bg=lightgray,fg=black}",
        "\\setbeamertemplate{navigation symbols}{}",
        # F4.4 T7 hotfix³: suppress Berlin's top navigation bar. Berlin's
        # default headline shows the deck's section/subsection structure,
        # but the new chain emits NO ``\section{}`` declarations, so the
        # bar renders empty/broken on every slide — the "all slides have
        # style issue" symptom the user reported. Mirrors the gold
        # reference deck (``D:/GitHub/Final_Report/slides.tex`` lines
        # 11-15) which suppresses all four templates together.
        "\\setbeamertemplate{headline}{}",
        "\\setbeamertemplate{section in head/foot}{}",
        "\\setbeamertemplate{subsection in head/foot}{}",
        "\\setbeamersize{text margin left=0.6cm, text margin right=0.6cm}",
        "",
        "\\setbeamertemplate{footline}{",
        "  \\leavevmode%",
        "  \\hbox{%",
        "  \\begin{beamercolorbox}"
        "[wd=.5\\paperwidth,ht=2.25ex,dp=1ex,right]"
        "{title in head/foot}%",
        "    \\usebeamerfont{title in head/foot}"
        "\\insertshorttitle\\hspace*{2ex}",
        "  \\end{beamercolorbox}%",
        "  \\begin{beamercolorbox}"
        "[wd=.5\\paperwidth,ht=2.25ex,dp=1ex,left]"
        "{date in head/foot}%",
        "    \\usebeamerfont{date in head/foot}"
        "\\hspace*{2ex}\\hfill"
        "\\insertframenumber{} / \\inserttotalframenumber"
        "\\hspace*{2ex}",
        "  \\end{beamercolorbox}}%",
        "  \\vskip0pt%",
        "}",
    ]
    if profile.needs_unicode_engine:
        # Magic comment MUST be line 1 of the source file so compile.py's
        # ``select_engine`` substring check (and any external editor) sees
        # it before the documentclass.
        head = ["% !TeX program = xelatex", *head]
    return head


def _resolve_theme(name: str) -> str:
    """Normalise + fall back: unknown values become ``GOLD`` (the default).

    A stray env-var typo (``PAPERHUB_SLIDE_THEME=goldd``) silently producing
    a metropolis deck would surprise the operator; falling back to the
    default keeps the surprise small."""
    norm = (name or "").strip().lower()
    return norm if norm in _KNOWN_THEMES else GOLD


def assemble_deck(inp: AssembleInput) -> str:
    theme = _resolve_theme(inp.theme)
    # Deck-content-aware Unicode detection (F4.4 T7 hotfix²). Any non-ASCII
    # character in the visible deck text — frames, title, subtitle, author —
    # flips the preamble into xelatex + fontspec mode (Cyrillic, Greek,
    # Arabic, Hebrew, Latin-Extended, etc.). CJK additionally pulls in
    # xeCJK. compile.py picks up the ``% !TeX program = xelatex`` magic
    # comment + ``ensure_main_unicode_font`` injects ``\setmainfont{Noto
    # Serif}`` (and ``ensure_cjk_font`` injects the CJK main font) at
    # compile time. Pure-ASCII decks keep pdflatex.
    profile = _unicode_profile(
        "".join(inp.frames), inp.title, inp.subtitle, inp.author
    )
    head = (
        _build_metropolis_preamble_head(profile=profile)
        if theme == METROPOLIS
        else _build_gold_preamble_head(profile=profile)
    )

    preamble: list[str] = [
        *head,
        build_graphicspath(inp.cache_source_dirs),
        build_additional_block(inp.additional_tex_macros),
        inp.paper_newcommands_block,
        f"\\title{{{inp.title}}}",
    ]
    if inp.subtitle:
        preamble.append(f"\\subtitle{{{inp.subtitle}}}")
    if inp.author:
        preamble.append(f"\\author{{{inp.author}}}")
    if inp.date:
        preamble.append(f"\\date{{{inp.date}}}")
    # Berlin theme's styled title band shrinks visibly when ``\institute{}``
    # is unset, producing the "bare title page" symptom the user reported.
    # Provide a small PaperHub wordmark as the default anchor; callers that
    # supply their own \institute via additional_tex_macros take precedence
    # since LaTeX honours the last definition.
    preamble.append(_DEFAULT_INSTITUTE)
    parts: list[str] = [
        *preamble,
        "\\begin{document}",
    ]
    if not inp.skip_title_injection:
        # Real, editable title frame (not bare \maketitle) so its layout can be
        # customized via the edit_title sub-flow (F4.2). Skipped when the
        # caller has already supplied a title frame in ``frames`` (F4.4 T5
        # planner ALWAYS emits one); otherwise the deck would carry two.
        parts.append("\\begin{frame}[plain]\n\\titlepage\n\\end{frame}")
    parts.extend(inp.frames)
    parts.append("\\end{document}")
    return "\n".join(p for p in parts if p) + "\n"
