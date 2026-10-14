"""The new Ichos mark and app icons (Fixer Upper S1/S3).

Why these checks: the icons ship as files other code points at (the tray, shortcuts, the favicon), so a missing or
broken file only shows up on the owner's PC. These tests catch that here, with no GPU, network or display.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

BRAND = Path(__file__).resolve().parent.parent / "assets" / "brand"
SVGS = ["ichos-mark.svg", "ichos-mark-small.svg", "ichos-icon.svg", "ichos-icon-small.svg"]
SVG_NS = "{http://www.w3.org/2000/svg}"


@pytest.mark.parametrize("name", SVGS)
def test_svg_is_plain_vector_art(name):
    root = ET.parse(BRAND / name).getroot()
    tags = {el.tag.replace(SVG_NS, "") for el in root.iter()}
    # Vector only: no scripts, no embedded pictures (the old favicon was a PNG inside an SVG).
    assert not tags & {"script", "image", "foreignObject"}
    assert root.get("viewBox") == "0 0 512 512"


@pytest.mark.parametrize("name", ["ichos-mark.svg", "ichos-mark-small.svg"])
def test_mark_is_one_colour_lighter_top_left(name):
    root = ET.parse(BRAND / name).getroot()
    grads = list(root.iter(f"{SVG_NS}linearGradient"))
    assert len(grads) == 1, "one colour family, one gradient"
    g = grads[0]
    # The gradient runs top-left to bottom-right, as the owner asked.
    assert float(g.get("x2")) > float(g.get("x1")) and float(g.get("y2")) > float(g.get("y1"))
    stops = [s.get("stop-color") for s in g.iter(f"{SVG_NS}stop")]
    lum = [sum(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in stops]
    assert lum == sorted(lum, reverse=True), "lightest stop first (top-left)"


@pytest.mark.parametrize("size", [16, 32, 48, 64, 128, 256, 512])
def test_png_sizes(size):
    from PIL import Image

    with Image.open(BRAND / f"ichos-icon-{size}.png") as im:
        assert im.size == (size, size)
        assert im.mode == "RGBA"


def test_windows_icon_has_small_and_large_sizes():
    from PIL import Image

    with Image.open(BRAND / "nyx.ico") as im:
        sizes = im.info.get("sizes", set())
    assert (16, 16) in sizes and (256, 256) in sizes
