"""F4.5 — defensive post-process that injects ``\\centering`` before
``\\includegraphics`` and a blank line after the figure block so the
following text breaks onto its own paragraph. Without it, CJK decks rendered
caption text inline to the RIGHT of the figure instead of below.
"""
from paperhub.agents.sl_emit import enforce_figure_paragraph_break


def test_injects_par_when_text_follows_includegraphics_inline() -> None:
    """The Chinese-deck failure: \\includegraphics + \\vspace + text on next non-empty line."""
    tex = (
        r"\begin{frame}{X}" "\n"
        r"  \includegraphics[width=\linewidth,height=0.6\textheight,keepaspectratio]{p0-fig-001}" "\n"
        r"  \vspace{0.3em}" "\n"
        r"  {\small Caption text.}" "\n"
        r"\end{frame}" "\n"
    )
    fixed = enforce_figure_paragraph_break(tex)
    # Must contain a paragraph break (blank line) between \vspace and {\small ...}.
    vspace_idx = fixed.find("\\vspace{0.3em}")
    text_idx = fixed.find("{\\small Caption", vspace_idx)
    between = fixed[vspace_idx:text_idx]
    assert "\n\n" in between, f"missing blank line between \\vspace and text: {between!r}"


def test_injects_centering_before_includegraphics() -> None:
    """The fix must inject ``\\centering`` on its own line before
    ``\\includegraphics`` when not already present."""
    tex = (
        r"\begin{frame}{X}" "\n"
        r"  \includegraphics[width=\linewidth]{p0-fig-001}" "\n"
        r"  \vspace{0.3em}" "\n"
        r"  {\small Caption.}" "\n"
        r"\end{frame}" "\n"
    )
    fixed = enforce_figure_paragraph_break(tex)
    centering_pos = fixed.find("\\centering")
    figure_pos = fixed.find("\\includegraphics")
    assert centering_pos != -1 and centering_pos < figure_pos


def test_injects_blank_line_after_vspace_before_caption() -> None:
    """The fix must inject a blank line BETWEEN ``\\vspace`` and the next text."""
    tex = (
        r"\begin{frame}{X}" "\n"
        r"  \includegraphics[width=\linewidth]{p0-fig-001}" "\n"
        r"  \vspace{0.3em}" "\n"
        r"  {\small Caption.}" "\n"
        r"\end{frame}" "\n"
    )
    fixed = enforce_figure_paragraph_break(tex)
    vspace_idx = fixed.find("\\vspace{0.3em}")
    text_idx = fixed.find("{\\small Caption", vspace_idx)
    between = fixed[vspace_idx:text_idx]
    assert "\n\n" in between, f"missing blank line between \\vspace and text: {between!r}"


def test_skips_centering_when_already_present() -> None:
    """Don't double-inject ``\\centering`` when it's already there."""
    tex = (
        r"\begin{frame}{X}" "\n"
        r"  \centering" "\n"
        r"  \includegraphics[width=\linewidth]{p0-fig-001}" "\n"
        r"  \vspace{0.3em}" "\n"
        r"" "\n"
        r"  {\small Caption.}" "\n"
        r"\end{frame}" "\n"
    )
    fixed = enforce_figure_paragraph_break(tex)
    assert fixed.count("\\centering") == 1


def test_idempotent_after_full_treatment() -> None:
    """Running the fixer twice on already-fixed tex produces the same result."""
    tex = (
        r"\begin{frame}{X}" "\n"
        r"  \includegraphics[width=\linewidth]{p0-fig-001}" "\n"
        r"  \vspace{0.3em}" "\n"
        r"  {\small Caption.}" "\n"
        r"\end{frame}" "\n"
    )
    once = enforce_figure_paragraph_break(tex)
    twice = enforce_figure_paragraph_break(once)
    assert once == twice


def test_idempotent_when_paragraph_break_already_present() -> None:
    """The English-deck pattern: blank line + \\centering already there → no change."""
    tex = (
        r"\begin{frame}{X}" "\n"
        r"  \centering" "\n"
        r"  \includegraphics[width=\linewidth]{p0-fig-001}" "\n"
        r"  \vspace{0.3em}" "\n"
        r"" "\n"
        r"  {\small Caption text.}" "\n"
        r"\end{frame}" "\n"
    )
    fixed = enforce_figure_paragraph_break(tex)
    # Running it again must produce the same result (idempotent).
    assert enforce_figure_paragraph_break(fixed) == fixed


def test_no_injection_inside_columns_block() -> None:
    """When ``\\includegraphics`` is inside a ``\\begin{column}{...}``, the
    column layout is already a side-by-side flow; don't inject."""
    tex = (
        r"\begin{frame}{X}" "\n"
        r"\begin{columns}[T]" "\n"
        r"  \begin{column}{0.5\textwidth}" "\n"
        r"    \includegraphics[width=\linewidth]{p0-fig-001}" "\n"
        r"  \end{column}" "\n"
        r"  \begin{column}{0.5\textwidth}" "\n"
        r"    \begin{itemize}\item bullet\end{itemize}" "\n"
        r"  \end{column}" "\n"
        r"\end{columns}" "\n"
        r"\end{frame}" "\n"
    )
    fixed = enforce_figure_paragraph_break(tex)
    # No \centering or blank-line injection inside columns.
    assert "\\centering" not in fixed
    assert fixed == tex


def test_no_injection_when_followed_by_end_frame() -> None:
    """``\\includegraphics`` immediately before ``\\end{frame}`` (no text) → no injection."""
    tex = (
        r"\begin{frame}{X}" "\n"
        r"  \includegraphics[width=\linewidth]{p0-fig-001}" "\n"
        r"\end{frame}" "\n"
    )
    fixed = enforce_figure_paragraph_break(tex)
    assert fixed == tex


def test_handles_multiple_figures_in_one_deck() -> None:
    """Multi-frame deck with multiple ``\\includegraphics`` + text patterns: each gets fixed."""
    tex = (
        r"\begin{frame}{A}" "\n"
        r"  \includegraphics[width=\linewidth]{p0-fig-001}" "\n"
        r"  \vspace{0.3em}" "\n"
        r"  {\small Caption A.}" "\n"
        r"\end{frame}" "\n"
        r"\begin{frame}{B}" "\n"
        r"  \includegraphics[width=\linewidth]{p0-fig-002}" "\n"
        r"  \vspace{0.3em}" "\n"
        r"  {\small Caption B.}" "\n"
        r"\end{frame}" "\n"
    )
    fixed = enforce_figure_paragraph_break(tex)
    # Both frames should have \centering injected and a blank line between
    # \vspace and {\small ...}.
    assert fixed.count("\\centering") == 2
    assert fixed.count("\n\n") >= 2
