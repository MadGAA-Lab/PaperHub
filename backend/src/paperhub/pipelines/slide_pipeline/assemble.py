"""Assemble a Beamer deck from generated section frames (new code).

Writes the preamble (theme + ADDITIONAL.tex), title frame, all section frames,
and a single \\graphicspath spanning every contributing paper's cache source
dir (SRS v2.18 §III-5.3 step 4a). Figures are never copied into the session dir.

F4.4 T8 (this refactor): the hardcoded preamble strings that accumulated
across F4.4 hotfixes (Unicode engine, headline suppression, default
institute, CJK) are gone. Style now flows from a yaml-driven
``SlideStyleProfile`` registry — see ``style_profile.py`` and
``slide_style_profiles.yaml``. ``assemble_deck`` resolves a profile by
name (``"default"`` ships as the Final_Report gold methodology;
``"metropolis_minimal"`` is the legacy minimal preamble) and walks the
profile fields through one data-driven emitter. Unknown profile names
are normalised to ``"default"`` so a stray env-var typo cannot silently
produce an unrelated deck.

The deck-content-aware Unicode detection (any non-ASCII codepoint trips
xelatex + the profile's ``requires_unicode_packages``; CJK additionally
pulls in ``requires_cjk_packages``) is unchanged from T7 hotfix² — the
profile just supplies the package names. ``compile.py``'s
``select_engine`` still picks up the ``% !TeX program = xelatex`` magic
comment; ``ensure_main_unicode_font`` / ``ensure_cjk_font`` still inject
the default Unicode / CJK main fonts at compile time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from paperhub.pipelines.slide_pipeline.style_profile import (
    SlideStyleProfile,
    list_profiles,
    load_profile,
)

# Default profile name when an unknown/missing value is passed in. The
# registry must always contain a profile of this name (see
# ``slide_style_profiles.yaml``); the assertion in ``_resolve_profile``
# guards against an operator deleting it.
DEFAULT_PROFILE = "default"

# Legacy theme aliases — the F4.4 T7 ``theme`` argument used these
# names ("gold" / "metropolis"). Settings.load_settings() also rewrites
# the legacy ``PAPERHUB_SLIDE_THEME`` env var via the same mapping so
# the chat → ReportDeps → assemble path is consistent end-to-end.
LEGACY_THEME_ALIASES = {
    "gold": "default",
    "metropolis": "metropolis_minimal",
}


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


@dataclass(frozen=True)
class UnicodeProfile:
    """Two-axis classification of a deck's visible text.

    ``needs_unicode_engine`` — ANY non-ASCII codepoint present. Trips the
    ``% !TeX program = xelatex`` magic comment + the profile's
    ``requires_unicode_packages`` (typically ``\\usepackage{fontspec}``)
    so the deck compiles under xelatex with a Unicode-capable main font
    (``compile.ensure_main_unicode_font`` injects ``\\setmainfont{Noto
    Serif}`` at compile time, covering Cyrillic / Greek / Arabic / Hebrew
    / Latin-Extended / etc.).

    ``needs_cjk`` — CJK codepoint present. Additionally pulls in the
    profile's ``requires_cjk_packages`` (typically
    ``\\usepackage{xeCJK}``; ``compile.ensure_cjk_font`` injects
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


def _resolve_profile(name: str) -> SlideStyleProfile:
    """Resolve a profile name to a loaded ``SlideStyleProfile``.

    Accepts the legacy F4.4 T7 aliases (``"gold"``, ``"metropolis"``)
    for backward compat. Unknown / empty values fall back to the
    default profile — a stray env-var typo silently producing an
    unrelated style would surprise the operator, and the env-var
    normaliser in ``config.load_settings`` mirrors this policy so the
    same fallback applies on the chat path.
    """
    norm = (name or "").strip().lower()
    norm = LEGACY_THEME_ALIASES.get(norm, norm)
    available = list_profiles()
    assert DEFAULT_PROFILE in available, (
        f"slide_style_profiles.yaml must define a {DEFAULT_PROFILE!r} profile"
    )
    if norm not in available:
        norm = DEFAULT_PROFILE
    return load_profile(norm)


def _format_color_def(name: str, spec: str) -> str:
    """Turn a ``"MODEL:value"`` envelope into a ``\\definecolor`` line.

    Splitting on the FIRST colon only — colour-model values themselves
    (``"RGB:0,90,160"``, ``"HTML:1A2B3C"``, ``"cmyk:0,0.5,0.5,0"``)
    never contain a colon before the model, but RGB values are
    comma-separated which CAN contain '0:1' style triples in exotic
    notations. ``partition`` makes the contract explicit.
    """
    model, sep, value = spec.partition(":")
    if not sep:
        # No model prefix — emit with empty model. Profiles should not
        # ship like this, but we don't want to crash the deck.
        return f"\\definecolor{{{name}}}{{}}{{{spec}}}"
    return f"\\definecolor{{{name}}}{{{model}}}{{{value}}}"


def _build_preamble_head(
    profile: SlideStyleProfile, unicode_profile: UnicodeProfile
) -> list[str]:
    """Emit the preamble from a profile + Unicode classification.

    Order (fixed; all sections are optional based on profile contents):

      1.  ``% !TeX program = xelatex`` magic comment (when Unicode needed)
      2.  ``\\documentclass[OPTIONS]{beamer}``
      3.  ``\\usepackage`` lines (profile.packages)
      4.  Unicode add-ons (profile.requires_unicode_packages)
      5.  CJK add-ons (profile.requires_cjk_packages)
      6.  ``\\usetheme`` + optional ``\\usecolortheme`` + ``\\usefonttheme``
      7.  Blank line separator (for readability of the generated .tex)
      8.  ``\\definecolor`` lines (profile.color_defs)
      9.  Blank line separator
      10. ``\\setbeamercolor`` overrides (profile.beamercolor_overrides)
      11. ``\\setbeamertemplate{NAME}{}`` blanks (profile.beamertemplate_suppressions)
      12. ``\\setbeamersize`` lines (profile.beamersize_settings)
      13. Blank line separator
      14. ``custom_footline_tex`` (verbatim multi-line block)

    The magic comment MUST be line 1 so ``compile.py``'s
    ``select_engine`` substring check (and any external editor) sees it
    before the documentclass.
    """
    head: list[str] = []
    opts = profile.document_class_options
    if opts:
        head.append(f"\\documentclass[{opts}]{{beamer}}")
    else:
        head.append("\\documentclass{beamer}")
    for pkg in profile.packages:
        head.append(f"\\usepackage{pkg}")
    if unicode_profile.needs_unicode_engine:
        for pkg in profile.requires_unicode_packages:
            head.append(f"\\usepackage{pkg}")
        if unicode_profile.needs_cjk:
            for pkg in profile.requires_cjk_packages:
                head.append(f"\\usepackage{pkg}")
    head.append("")
    head.append(f"\\usetheme{{{profile.theme}}}")
    if profile.colortheme:
        head.append(f"\\usecolortheme{{{profile.colortheme}}}")
    if profile.fonttheme:
        head.append(f"\\usefonttheme{{{profile.fonttheme}}}")
    if profile.color_defs:
        head.append("")
        for color_name, spec in profile.color_defs.items():
            head.append(_format_color_def(color_name, spec))
    if profile.beamercolor_overrides or profile.beamertemplate_suppressions:
        head.append("")
        for element, spec in profile.beamercolor_overrides.items():
            head.append(f"\\setbeamercolor{{{element}}}{{{spec}}}")
        for template_name in profile.beamertemplate_suppressions:
            head.append(f"\\setbeamertemplate{{{template_name}}}{{}}")
    for size_spec in profile.beamersize_settings:
        head.append(f"\\setbeamersize{{{size_spec}}}")
    if profile.custom_footline_tex:
        head.append("")
        head.append(profile.custom_footline_tex)
    if unicode_profile.needs_unicode_engine:
        head = ["% !TeX program = xelatex", *head]
    return head


def _resolve_theme(name: str) -> str:
    """Backward-compat shim — returns the resolved profile NAME.

    F4.4 T8: callers that just want to know "what profile did we end
    up with?" use this; the actual ``SlideStyleProfile`` lookup
    happens inside ``_resolve_profile``. Kept module-level so the
    ``decks.theme`` column wiring and any external test that depended
    on this helper still has a stable name.
    """
    return _resolve_profile(name).name


def assemble_deck(inp: AssembleInput) -> str:
    profile = _resolve_profile(inp.theme)
    # Deck-content-aware Unicode detection. Any non-ASCII character in
    # the visible deck text — frames, title, subtitle, author — flips
    # the preamble into xelatex + the profile's ``requires_unicode``
    # packages (Cyrillic, Greek, Arabic, Hebrew, Latin-Extended, etc.).
    # CJK additionally pulls in ``requires_cjk``. compile.py picks up
    # the ``% !TeX program = xelatex`` magic comment + the font helpers
    # inject the default fonts at compile time. Pure-ASCII decks keep
    # pdflatex (faster compile path).
    unicode_profile = _unicode_profile(
        "".join(inp.frames), inp.title, inp.subtitle, inp.author
    )
    head = _build_preamble_head(profile, unicode_profile)

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
    # is unset, producing the "bare title page" symptom an earlier hotfix
    # targeted. The default anchor lives on the profile (operators can edit
    # it via the yaml without code changes); callers that supply their own
    # \institute via additional_tex_macros take precedence since LaTeX
    # honours the last definition.
    if profile.default_institute_tex:
        preamble.append(profile.default_institute_tex)
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
