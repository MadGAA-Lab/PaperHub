"""Pre-rasterise complex LaTeX tables so pandoc can embed them as <img>.

Pandoc cannot parse the ``tabular*`` / ``tabularx`` environments at all (it
emits ``<div class="tabular*">`` and dumps the column spec + every &-separated
cell as raw text), and it mishandles ``\\multirow`` / ``\\makecell`` / dense
``\\multicolumn``+``\\cmidrule`` tables. arXiv:2602.20200's RoboTwin comparison
table (a 14-column ``tabular*`` with ``\\multirow`` headers) is the motivating
case. This module compiles each such table as a ``standalone`` document via
``pdflatex``, rasterises it to PNG, and rewrites the grid environment to
``\\includegraphics`` — leaving the surrounding ``table`` float + ``\\caption``
in place so pandoc still renders the caption as selectable text.

Mirrors ``tikz_figures.rasterize_tikz_figures``: ``pdflatex`` is already a hard
slide-pipeline dependency, failures are graceful (an un-compilable table is left
as-is), and the whole pass is a no-op when ``pdflatex`` is absent.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# A plain ``tabular`` is hostile only if its body uses constructs pandoc
# mishandles; ``tabular*`` / ``tabularx`` are hostile by environment.
_HOSTILE_BODY_RE = re.compile(r"\\multirow|\\makecell")
_MULTICOLUMN_RE = re.compile(r"\\multicolumn")
_CMIDRULE_RE = re.compile(r"\\cmidrule")


def _is_hostile(env_name: str, body: str) -> bool:
    """True if a table environment can't be reliably rendered by pandoc."""
    if env_name in ("tabular*", "tabularx"):
        return True
    if _HOSTILE_BODY_RE.search(body):
        return True
    return bool(_MULTICOLUMN_RE.search(body) and _CMIDRULE_RE.search(body))
