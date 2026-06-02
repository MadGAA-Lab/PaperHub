"""F4.5 — defensive post-process that injects ``\\par`` between
``\\includegraphics`` (+ trailing ``\\vspace``) and the next text content
when the LLM omitted the blank line. Without it, CJK decks rendered
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
    # Must contain a paragraph break (blank line or \par) between \vspace and {\small ...}
    assert "\\par" in fixed or "\n\n  {\\small" in fixed


def test_idempotent_when_paragraph_break_already_present() -> None:
    """The English-deck pattern: blank line already there → no change."""
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
    """When \\includegraphics is inside a \\begin{column}{...}, the column layout
    is already a side-by-side flow; don't inject."""
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
    # Inside the column, the includegraphics shouldn't get a \par injected
    # (the column ends right after, and the next content is in a separate column).
    assert fixed == tex


def test_no_injection_when_followed_by_end_frame() -> None:
    """\\includegraphics immediately before \\end{frame} (no text) → no injection."""
    tex = (
        r"\begin{frame}{X}" "\n"
        r"  \includegraphics[width=\linewidth]{p0-fig-001}" "\n"
        r"\end{frame}" "\n"
    )
    fixed = enforce_figure_paragraph_break(tex)
    assert fixed == tex


def test_handles_multiple_figures_in_one_deck() -> None:
    """Multi-frame deck with multiple \\includegraphics + text patterns: each gets fixed."""
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
    # Both frames should have paragraph breaks injected.
    # Count \par insertions or blank lines.
    assert fixed.count("\\par") >= 2 or fixed.count("\n\n  {\\small") >= 2
