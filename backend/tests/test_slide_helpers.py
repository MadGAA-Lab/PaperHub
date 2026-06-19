from paperhub.pipelines.slide_pipeline.beamer_helpers import (
    extract_frames_from_beamer,
    get_frame_by_number,
    replace_frame_in_beamer,
)
from paperhub.pipelines.slide_pipeline.latex_helpers import (
    build_additional_tex,
    extract_definitions_and_usepackage_lines,
    sanitize_frametitles,
)


def test_extract_defs_and_build_additional() -> None:
    src = r"""\documentclass{article}
\usepackage{amsmath}
\newcommand{\bx}{\mathbf{x}}
\DeclareMathOperator{\softmax}{softmax}
\begin{document}\end{document}"""
    defs = extract_definitions_and_usepackage_lines(src)
    add = build_additional_tex(defs)
    assert "\\newcommand{\\bx}" in add
    assert "\\DeclareMathOperator{\\softmax}" in add


def test_frame_roundtrip() -> None:
    beamer = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\begin{frame}{A}\\end{frame}\n"
        "\\begin{frame}{B}\\end{frame}\n"
        "\\end{document}\n"
    )
    frames = extract_frames_from_beamer(beamer)
    assert len(frames) == 2
    assert frames[0][0] == 1
    f2 = get_frame_by_number(beamer, 2)
    assert f2 is not None and "{B}" in f2
    out = replace_frame_in_beamer(beamer, 2, "\\begin{frame}{B2}\\end{frame}")
    assert out is not None and "{B2}" in out


def test_sanitize_frametitles_escapes_ampersand() -> None:
    assert "\\&" in sanitize_frametitles("\\frametitle{Cats & Dogs}")


def test_sanitize_frametitles_options_and_overlay_preserved() -> None:
    # Overlay <...>, short-title [...], and the main {...} all survive, with
    # ampersands escaped in each — guards the de-ambiguated frametitle regex.
    out = sanitize_frametitles("\\frametitle <1-> [A & B] {Main & Title}")
    assert "<1->" in out and "A \\& B" in out and "Main \\& Title" in out


def test_sanitize_frame_env_title_escaped() -> None:
    out = sanitize_frametitles("\\begin{frame}[fragile]{X & Y}\\end{frame}")
    assert "[fragile]" in out and "X \\& Y" in out


def test_sanitize_repairs_first_mistaken_gt_only() -> None:
    # \end{frame> and \begin{itemize> are two independent typos; each is
    # repaired at its OWN first '>', not swallowed together.
    out = sanitize_frametitles("\\end{frame> \\begin{itemize>")
    assert "\\end{frame}" in out and "\\begin{itemize}" in out


def test_sanitize_frametitles_linear_on_pathological_input() -> None:
    # Unterminated frametitle with a long whitespace run must not backtrack
    # super-linearly (CodeQL py/polynomial-redos). Bound the wall time well
    # under any backtracking blow-up.
    import time

    payload = "\\frametitle " + " " * 200_000 + "X"
    start = time.perf_counter()
    sanitize_frametitles(payload)
    assert time.perf_counter() - start < 1.0
