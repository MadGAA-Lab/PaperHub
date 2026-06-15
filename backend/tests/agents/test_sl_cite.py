from paperhub.agents.sl_cite import (
    content_cites,
    detect_cite_violations,
    parse_cite,
)

_VALID = {(7, "method"), (7, "results")}

_DECK = r"""\documentclass{beamer}
\begin{document}
\begin{frame}[plain]
% cite: title
\titlepage
\end{frame}
\begin{frame}{Method}
% cite: 7:Method
\begin{itemize}\item maps positions to rotations\end{itemize}
\end{frame}
\begin{frame}{Unsourced}
% cite: hallucination
\begin{itemize}\item something\end{itemize}
\end{frame}
\begin{frame}{Bad section}
% cite: 7:Nonexistent
\begin{itemize}\item x\end{itemize}
\end{frame}
\begin{frame}{No marker at all}
\begin{itemize}\item y\end{itemize}
\end{frame}
\begin{frame}{Fake divider}
% cite: divider
\includegraphics{p0-fig-001}
\end{frame}
\end{document}
"""


def test_parse_cite_kinds() -> None:
    assert parse_cite("% cite: title\n\\titlepage") == ("title", [])
    assert parse_cite("% cite: hallucination") == ("hallucination", [])
    assert parse_cite("% cite: 7:Method; 7:Results")[0] == "content"
    assert parse_cite("% cite: 7:Method")[1] == [(7, "Method")]
    assert parse_cite("no marker here") is None


def test_detect_cite_violations_flags_the_right_frames() -> None:
    v = {(s.frame_index, s.reason) for s in detect_cite_violations(_DECK, _VALID)}
    # frame 0 title OK; frame 1 valid content OK.
    assert (2, "hallucination") in v        # cite: hallucination
    assert (3, "no_evidence") in v          # cites a section with no chunks
    assert (4, "missing") in v              # no marker
    assert (5, "fake_structural") in v      # cite:divider but has a figure
    # the valid frames are not flagged
    assert not any(fi in {0, 1} for fi, _ in v)


def test_detect_cite_violations_stands_down_without_evidence() -> None:
    # No evidence set => gate off (nothing to ground against).
    assert detect_cite_violations(_DECK, set()) == []


def test_content_cites_aligns_by_frame() -> None:
    cc = dict(content_cites(_DECK))
    assert cc[1] == [(7, "Method")]   # the content frame's cited section
    assert cc[0] == []                # title frame -> no content cite
