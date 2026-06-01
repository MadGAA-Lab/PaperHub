"""F4.5 figure geometry — PIL probe + \\includegraphics resolver.

The slide_agent + overflow_detector need to know how much canvas a
``\\includegraphics[width=W,height=H,keepaspectratio]{key}`` actually consumes
in cm. With keepaspectratio (the F4.5 norm), the smaller of (w_request,
h_request × aspect) wins.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from paperhub.models.slide_domain import FigureDimensions

_LOG = logging.getLogger(__name__)

# \linewidth and \textheight at 16:9 14pt Beamer with the F4.5 default
# preamble's margins. Empirically measured (paper2slides-plus default at
# aspectratio=169 — ~12.8cm width, ~6.5cm body height after headline/footline).
# Operators tune these via slide_canvas_budget.yaml in Phase 3.
LINEWIDTH_CM_DEFAULT = 12.8
TEXTHEIGHT_CM_DEFAULT = 6.5

# Matches \includegraphics, optionally with options [k=v,...], then {key}.
_INCLUDEGRAPHICS_RE = re.compile(
    r"\\includegraphics(?:\[(?P<opts>[^\]]*)\])?\{(?P<key>[^}]+)\}"
)


def probe_figure_dimensions(path: Path | str) -> FigureDimensions:
    """Read width_px / height_px via PIL.

    Soft-fails to a neutral 1:1 default on unreadable files — the detector
    treats unknown aspect as 'no aspect constraint', so a missing probe
    degrades gracefully rather than crashing the gather_context fan-out.
    """
    try:
        from PIL import Image

        with Image.open(str(path)) as im:
            w, h = im.size
        if w <= 0 or h <= 0:
            raise ValueError(f"degenerate dimensions {w}x{h}")
        return FigureDimensions(width_px=w, height_px=h)
    except Exception as exc:  # noqa: BLE001 — best-effort probe
        _LOG.warning("probe_figure_dimensions failed for %s: %r", path, exc)
        return FigureDimensions(width_px=1000, height_px=1000)


def parse_includegraphics_options(tex: str) -> dict[str, object]:
    """Parse ONE \\includegraphics call. Returns:

      {
        'key': <stem>,
        'width_spec': <raw spec str or None>,    # e.g. '0.5\\linewidth', '8cm'
        'height_spec': <raw spec str or None>,
        'keepaspectratio': bool,
      }

    If multiple \\includegraphics calls appear in `tex`, the first wins —
    callers parsing a whole frame should iterate matches separately.
    """
    m = _INCLUDEGRAPHICS_RE.search(tex)
    if m is None:
        return {"key": None, "width_spec": None, "height_spec": None, "keepaspectratio": False}
    opts_raw = (m.group("opts") or "").strip()
    width_spec: str | None = None
    height_spec: str | None = None
    keepaspectratio = False
    for part in opts_raw.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "keepaspectratio":
            keepaspectratio = True
            continue
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        k = k.strip().lower()
        v = v.strip()
        if k == "width":
            width_spec = v
        elif k == "height":
            height_spec = v
    return {
        "key": m.group("key"),
        "width_spec": width_spec,
        "height_spec": height_spec,
        "keepaspectratio": keepaspectratio,
    }


_SPEC_RE = re.compile(
    r"^(?P<coef>\d*\.?\d*)\s*(?P<unit>\\linewidth|\\textwidth|\\textheight|\\paperwidth|\\paperheight|cm|mm|pt|in)?$"
)


def _spec_to_cm(spec: str | None, linewidth_cm: float, textheight_cm: float) -> float | None:
    """Resolve a LaTeX dimension spec like '0.5\\linewidth' / '8cm' to cm.

    Unknown / malformed specs return None (caller treats as 'unconstrained').
    Bare numeric coefficients (no unit, e.g. '0.5') are taken as a fraction
    of linewidth — that's how Beamer interprets them in \\includegraphics.
    """
    if spec is None:
        return None
    m = _SPEC_RE.match(spec.strip())
    if m is None:
        return None
    coef_s = m.group("coef") or ""
    unit = m.group("unit") or ""
    try:
        coef = float(coef_s) if coef_s else 1.0
    except ValueError:
        return None
    if unit in ("", "\\linewidth", "\\textwidth", "\\paperwidth"):
        return coef * linewidth_cm
    if unit in ("\\textheight", "\\paperheight"):
        return coef * textheight_cm
    if unit == "cm":
        return coef
    if unit == "mm":
        return coef / 10.0
    if unit == "pt":
        return coef * 0.0353  # 1pt ≈ 0.0353cm
    if unit == "in":
        return coef * 2.54
    return None


def resolve_includegraphics_geometry(
    *,
    width_spec: str | None,
    height_spec: str | None,
    keepaspectratio: bool,
    aspect_ratio: float,
    linewidth_cm: float = LINEWIDTH_CM_DEFAULT,
    textheight_cm: float = TEXTHEIGHT_CM_DEFAULT,
) -> tuple[float, float]:
    """Return the actual rendered (width_cm, height_cm) of one \\includegraphics.

    With keepaspectratio, the figure scales uniformly to fit the smaller of
    the two request bounds — width-bound or height-bound. Without it, both
    requests are honoured (the figure stretches; the F4.5 default + the
    slide_agent prompt steer toward keepaspectratio=True).

    When no width/height specs are given, defaults to width=\\linewidth.
    """
    w_req = _spec_to_cm(width_spec, linewidth_cm, textheight_cm)
    h_req = _spec_to_cm(height_spec, linewidth_cm, textheight_cm)

    if w_req is None and h_req is None:
        w_req = linewidth_cm  # the Beamer default

    if not keepaspectratio:
        # Both honoured as given. Fall back to natural-aspect height when one missing.
        w_cm = w_req if w_req is not None else (h_req or textheight_cm) * aspect_ratio
        h_cm = h_req if h_req is not None else (w_req or linewidth_cm) / aspect_ratio
        return w_cm, h_cm

    # With keepaspectratio: try to fit BOTH bounds; smaller wins.
    candidates: list[tuple[float, float]] = []
    if w_req is not None:
        candidates.append((w_req, w_req / aspect_ratio))
    if h_req is not None:
        candidates.append((h_req * aspect_ratio, h_req))
    # Pick the candidate with the SMALLER footprint (uniform scale-to-fit).
    w_cm, h_cm = min(candidates, key=lambda wh: wh[0] * wh[1])
    return w_cm, h_cm
