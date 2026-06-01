import pytest
from PIL import Image

from paperhub.pipelines.slide_pipeline.figure_geometry import (
    parse_includegraphics_options,
    probe_figure_dimensions,
    resolve_includegraphics_geometry,
)


def test_probe_figure_dimensions_reads_real_png(tmp_path):
    path = tmp_path / "x.png"
    Image.new("RGB", (1640, 920), color=(255, 255, 255)).save(path)
    dims = probe_figure_dimensions(path)
    assert dims.width_px == 1640
    assert dims.height_px == 920


def test_probe_falls_back_to_square_default_on_unreadable_file(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not a real PNG")
    dims = probe_figure_dimensions(path)
    assert dims.width_px == 1000
    assert dims.height_px == 1000  # 1:1 default — neutral


def test_parse_includegraphics_options():
    opts = parse_includegraphics_options(
        r"\includegraphics[width=0.5\linewidth,height=0.6\textheight,keepaspectratio]{p0-fig-001}"
    )
    assert opts["key"] == "p0-fig-001"
    assert opts["width_spec"] == "0.5\\linewidth"
    assert opts["height_spec"] == "0.6\\textheight"
    assert opts["keepaspectratio"] is True


def test_parse_includegraphics_no_options():
    opts = parse_includegraphics_options(r"\includegraphics{foo}")
    assert opts["key"] == "foo"
    assert opts["width_spec"] is None
    assert opts["height_spec"] is None
    assert opts["keepaspectratio"] is False


def test_resolve_geometry_landscape_full_width_capped_by_height():
    # 16:9 figure (aspect 1.78). width=\linewidth (~12.8cm) would render as
    # 12.8 × 7.2cm — exceeds the 6.5cm canvas height. keepaspectratio shrinks
    # to fit: width becomes 6.5 × 1.78 = 11.57cm at 6.5cm tall.
    w_cm, h_cm = resolve_includegraphics_geometry(
        width_spec="\\linewidth",
        height_spec="\\textheight",
        keepaspectratio=True,
        aspect_ratio=1.78,
        linewidth_cm=12.8,
        textheight_cm=6.5,
    )
    assert w_cm == pytest.approx(6.5 * 1.78, rel=1e-3)
    assert h_cm == pytest.approx(6.5, rel=1e-3)


def test_resolve_geometry_portrait_half_width_fits_within_height():
    # 2:3 portrait figure (aspect 0.667). width=0.5\linewidth (6.4cm) →
    # height would be 6.4 / 0.667 = 9.6cm but capped by textheight 6.5 →
    # final 6.5 × 0.667 = 4.33cm wide × 6.5cm tall (height-bound).
    w_cm, h_cm = resolve_includegraphics_geometry(
        width_spec="0.5\\linewidth",
        height_spec="\\textheight",
        keepaspectratio=True,
        aspect_ratio=0.667,
        linewidth_cm=12.8,
        textheight_cm=6.5,
    )
    assert w_cm == pytest.approx(6.5 * 0.667, rel=1e-2)
    assert h_cm == pytest.approx(6.5, rel=1e-3)


def test_resolve_geometry_no_keepaspectratio_stretches():
    # Without keepaspectratio, both specs are honoured as given.
    w_cm, h_cm = resolve_includegraphics_geometry(
        width_spec="0.5\\linewidth",
        height_spec="0.4\\textheight",
        keepaspectratio=False,
        aspect_ratio=1.78,
        linewidth_cm=12.8,
        textheight_cm=6.5,
    )
    assert w_cm == pytest.approx(6.4)
    assert h_cm == pytest.approx(2.6)
