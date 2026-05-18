import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from paperhub.pipelines.renderer import render_html


def test_render_pdf_uses_pymupdf(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "papers" / "sample.pdf"
    out = tmp_path / "source.html"
    render_html(source=fixture, kind="pdf", out_path=out)
    html = out.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>") or html.startswith("<html")
    assert "Tiny Test Paper" in html


def test_render_latex_with_pandoc_when_available(tmp_path: Path) -> None:
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc binary not installed")
    fixture = Path(__file__).parent / "fixtures" / "papers" / "arxiv_sample" / "main.tex"
    out = tmp_path / "source.html"
    render_html(source=fixture, kind="latex", out_path=out)
    html = out.read_text(encoding="utf-8")
    assert "<h1" in html or "<h2" in html  # pandoc emits heading tags
    assert "Mixture-of-Experts" in html


def test_render_latex_falls_back_when_pandoc_missing(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "papers" / "arxiv_sample" / "main.tex"
    out = tmp_path / "source.html"
    with patch("paperhub.pipelines.renderer.shutil.which", return_value=None):
        render_html(source=fixture, kind="latex", out_path=out)
    html = out.read_text(encoding="utf-8")
    # pylatexenc fallback gives plainer output but should contain the body text.
    assert "Mixture-of-Experts" in html


def test_render_latex_pandoc_resolves_input_relative_to_source_dir(tmp_path: Path) -> None:
    """Pandoc must resolve \\input{...} relative to the .tex file's own directory,
    not the process cwd. Otherwise multi-file arxiv sources break silently."""
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc binary not installed")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.tex").write_text(
        r"\documentclass{article}\begin{document}"
        r"\input{intro}\end{document}",
        encoding="utf-8",
    )
    (src_dir / "intro.tex").write_text(
        "This is the included introduction text from a separate file.",
        encoding="utf-8",
    )
    out = tmp_path / "source.html"
    render_html(source=src_dir / "main.tex", kind="latex", out_path=out)
    html = out.read_text(encoding="utf-8")
    assert "included introduction text from a separate file" in html
