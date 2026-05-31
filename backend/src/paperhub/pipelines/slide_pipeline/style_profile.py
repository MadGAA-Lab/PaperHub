"""F4.4 T8 — yaml-driven ``SlideStyleProfile`` registry.

This module exists to KILL the hardcoded-preamble anti-pattern that
accumulated across F4.4's first four hotfixes (Unicode engine,
headline suppression, default institute, CJK). Every style choice
that previously lived as a Python string literal in ``assemble.py`` —
documentclass options, package list, theme/colortheme/fonttheme,
accent colours, beamercolor overrides, beamertemplate suppressions,
beamersize settings, the custom footline, the default institute, and
the Unicode/CJK package add-ons — now lives in
``slide_style_profiles.yaml`` as a data-only ``SlideStyleProfile``.

The user-edit surface for default deck style is THAT YAML FILE. The
operator opens the yaml, edits a profile (or adds a new one), and the
next ``assemble_deck`` call picks it up — no Python change needed. A
chat-side per-deck override (F4.2's ``edit_preamble`` action) is still
the path for a single deck; this profile is the project-wide DEFAULT.

The dataclass is intentionally data-only — no LaTeX-emission methods.
All emission stays in ``assemble.py``'s ``_build_preamble_head`` which
walks the profile fields in a fixed order. Splitting "what" (data
here) from "how" (rendering there) is the load-bearing refactor.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Any

import yaml


@dataclass(frozen=True)
class SlideStyleProfile:
    """A complete Beamer preamble specification.

    Every field maps 1:1 to a piece of the preamble emitted by
    ``assemble._build_preamble_head``. See
    ``slide_style_profiles.yaml`` for the canonical contents shipped
    with PaperHub and the comment block at the top of that file for
    operator-facing notes on editing.
    """

    name: str
    """Profile identifier — must be unique in the registry.

    Stored on the ``decks.theme`` column (backward-compat with
    dashboards / API consumers that look up the deck's style).
    """

    description: str
    """Human-readable one-liner — surfaced when an unknown profile
    name is requested (the error lists every available profile +
    description so an operator can pick the right one).
    """

    document_class_options: str
    """Bracketed options passed to ``\\documentclass[OPTIONS]{beamer}``.

    Empty string means ``\\documentclass{beamer}`` with no options.
    """

    packages: list[str]
    """Each entry is the ARGUMENT to ``\\usepackage``, e.g.
    ``"[T1]{fontenc}"`` → ``\\usepackage[T1]{fontenc}``, or
    ``"{graphicx}"`` → ``\\usepackage{graphicx}``. The leading bracket
    (or absence of one) selects whether package options are emitted.
    """

    theme: str
    """Beamer theme name — emitted as ``\\usetheme{<theme>}``."""

    colortheme: str | None
    """Optional colortheme — emitted as ``\\usecolortheme{<...>}``
    when set; entirely skipped when None.
    """

    fonttheme: str | None
    """Optional fonttheme — emitted as ``\\usefonttheme{<...>}``
    when set; entirely skipped when None.
    """

    color_defs: dict[str, str]
    """Mapping ``name → "MODEL:value"`` (e.g.
    ``"accent": "RGB:0,90,160"``). Emitted as
    ``\\definecolor{name}{MODEL}{value}``. The "MODEL:value" envelope
    keeps the yaml line scalar — no nested dict per colour — while
    still letting profiles mix RGB, HTML, cmyk, etc.
    """

    beamercolor_overrides: dict[str, str]
    """Mapping element-name → key-value spec (e.g.
    ``"block title": "bg=accent,fg=white"``). Emitted as
    ``\\setbeamercolor{<key>}{<value>}``.
    """

    beamertemplate_suppressions: list[str]
    """Template names to BLANK (e.g. ``"headline"``,
    ``"navigation symbols"``). Each emits
    ``\\setbeamertemplate{<name>}{}`` — the empty braces are the
    "suppress" idiom.
    """

    beamersize_settings: list[str]
    """Each entry is the ARGUMENT to ``\\setbeamersize`` (e.g.
    ``"text margin left=0.6cm, text margin right=0.6cm"``).
    """

    custom_footline_tex: str
    """Raw multi-line LaTeX for the footline override (the full
    ``\\setbeamertemplate{footline}{...}`` block, or empty string to
    skip). Emitted verbatim — the yaml literal-block syntax (``|``)
    preserves newlines.
    """

    default_institute_tex: str
    """Raw LaTeX emitted for ``\\institute{...}`` when no
    caller-supplied institute is present.

    The Berlin theme's coloured title band collapses visibly when
    ``\\institute`` is unset (the "bare title page" symptom an
    earlier hotfix targeted); a small wordmark anchors it.
    """

    requires_unicode_packages: list[str]
    """Extra ``\\usepackage`` entries when the deck contains
    non-ASCII text (Cyrillic, Greek, Latin-Extended, CJK, …).
    ``compile.py``'s ``select_engine`` switches to xelatex on the
    presence of the magic comment ``% !TeX program = xelatex``, and
    ``ensure_main_unicode_font`` injects the actual Unicode main font
    at compile time. Same format as ``packages`` (e.g. ``"{fontspec}"``).
    """

    requires_cjk_packages: list[str]
    """Extra ``\\usepackage`` entries when the deck contains CJK text
    (in ADDITION to the unicode packages — CJK is a strict superset
    of "non-ASCII"). Same format as ``packages``.
    """


# Cache parsed registry; lookups don't repeat the yaml read.
_REGISTRY_CACHE: dict[str, SlideStyleProfile] | None = None


def _load_registry() -> dict[str, SlideStyleProfile]:
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE
    path = files("paperhub.pipelines.slide_pipeline") / "slide_style_profiles.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(
            "slide_style_profiles.yaml must be a mapping with a top-level "
            "'profiles' key"
        )
    raw_profiles = data.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ValueError(
            "slide_style_profiles.yaml must declare at least one profile "
            "under 'profiles'"
        )
    registry: dict[str, SlideStyleProfile] = {}
    for name, spec in raw_profiles.items():
        registry[name] = _profile_from_dict(name, spec)
    _REGISTRY_CACHE = registry
    return registry


def _profile_from_dict(name: str, spec: dict[str, Any]) -> SlideStyleProfile:
    if not isinstance(spec, dict):
        raise ValueError(f"profile {name!r}: expected a mapping, got {type(spec).__name__}")

    def _str(key: str, default: str = "") -> str:
        value = spec.get(key, default)
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError(f"profile {name!r}: {key!r} must be a string")
        return value

    def _opt_str(key: str) -> str | None:
        value = spec.get(key)
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError(f"profile {name!r}: {key!r} must be a string or null")
        return value

    def _str_list(key: str) -> list[str]:
        value = spec.get(key) or []
        if not isinstance(value, list):
            raise ValueError(f"profile {name!r}: {key!r} must be a list of strings")
        out: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(
                    f"profile {name!r}: every entry in {key!r} must be a string"
                )
            out.append(item)
        return out

    def _str_dict(key: str) -> dict[str, str]:
        value = spec.get(key) or {}
        if not isinstance(value, dict):
            raise ValueError(f"profile {name!r}: {key!r} must be a mapping")
        out: dict[str, str] = {}
        for k, v in value.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError(
                    f"profile {name!r}: every entry in {key!r} must map "
                    "string → string"
                )
            out[k] = v
        return out

    return SlideStyleProfile(
        name=name,
        description=_str("description"),
        document_class_options=_str("document_class_options"),
        packages=_str_list("packages"),
        theme=_str("theme"),
        colortheme=_opt_str("colortheme"),
        fonttheme=_opt_str("fonttheme"),
        color_defs=_str_dict("color_defs"),
        beamercolor_overrides=_str_dict("beamercolor_overrides"),
        beamertemplate_suppressions=_str_list("beamertemplate_suppressions"),
        beamersize_settings=_str_list("beamersize_settings"),
        custom_footline_tex=_str("custom_footline_tex"),
        default_institute_tex=_str("default_institute_tex"),
        requires_unicode_packages=_str_list("requires_unicode_packages"),
        requires_cjk_packages=_str_list("requires_cjk_packages"),
    )


def load_profile(name: str) -> SlideStyleProfile:
    """Look up a profile by name.

    Unknown names raise ``LookupError`` listing every available
    profile + its description. Silent fallback to ``"default"`` is
    DELIBERATELY not done here — that policy lives in ``config.py``'s
    env-var normalisation, so the operator sees a clear error when
    code calls this with a typo'd name.
    """
    registry = _load_registry()
    if name not in registry:
        available = "\n".join(
            f"  - {n}: {p.description}" for n, p in registry.items()
        )
        raise LookupError(
            f"Unknown slide style profile {name!r}. Available profiles:\n"
            f"{available}"
        )
    return registry[name]


def list_profiles() -> list[str]:
    """Available profile names, in registry order.

    Used for error messages here and (eventually) by a chat-command
    "list slide styles" UX. Currently the registry is fixed at two
    entries shipped with PaperHub; operators can edit the yaml to add
    more.
    """
    return list(_load_registry().keys())


__all__ = [
    "SlideStyleProfile",
    "load_profile",
    "list_profiles",
]
