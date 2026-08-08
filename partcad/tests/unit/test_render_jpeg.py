#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for rendering 2D projections to JPEG.

JPEG shares the whole rasterization path with PNG (see
'wrappers/wrapper_render_raster.py'); what is specific to it is the file
extension, the encoder options and the background the transparent projection is
flattened onto. These tests cover that without the sandbox: an end-to-end render
is exercised by 'test_render.test_render_project' (the 'feature_export' example
renders JPEG) and by 'features/render.feature'.
"""

import importlib.util
import os
import sys
import types

import pytest

import partcad as pc
from partcad.shape import PART_EXTENSION_MAPPING, RENDER_EXTENSION_MAPPING, SERIALIZED_PART_TYPES

WRAPPERS_DIR = os.path.join(os.path.dirname(pc.__file__), "wrappers")


def _load_wrapper(name, stubs):
    """Import a render wrapper by path with its sandbox-only imports stubbed.

    The wrappers run inside a render sandbox that has svglib, reportlab and the
    CAD stack installed; the environment running these tests has none of them,
    so the modules they import are replaced by recorders.
    """
    saved = {key: sys.modules.get(key) for key in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location("test_%s" % name, os.path.join(WRAPPERS_DIR, "%s.py" % name))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in saved.items():
            if value is None:
                del sys.modules[key]
            else:
                sys.modules[key] = value


def _raster_stub():
    """A stand-in for 'wrapper_render_raster' that records how it was called."""
    stub = types.ModuleType("wrapper_render_raster")
    stub.calls = []

    def process(path, request, fmt, config_pil=None):
        stub.calls.append((path, request, fmt, config_pil))
        return {"success": True, "exception": None}

    stub.process = process
    return stub


def _jpeg_wrapper():
    raster = _raster_stub()
    module = _load_wrapper(
        "wrapper_render_jpeg",
        {"wrapper_common": types.ModuleType("wrapper_common"), "wrapper_render_raster": raster},
    )
    return module, raster


def test_jpeg_extension_is_jpg():
    """The format is named "jpeg" but the file it writes is a ".jpg"."""
    assert RENDER_EXTENSION_MAPPING["jpeg"] == "jpg"
    # The render-only mapping stays out of the part type mappings: a rasterized
    # projection is not something a part can be defined by, so 'convert()' must
    # not start offering it.
    assert "jpeg" not in PART_EXTENSION_MAPPING
    assert "jpeg" not in SERIALIZED_PART_TYPES


def test_jpeg_render_getopts_uses_the_jpg_extension():
    """A package's JPEG render options resolve to a '<name>.jpg' output path."""
    ctx = pc.init("examples")
    prj = ctx.get_project("//feature_export")
    bolt = prj.get_part("bolt")
    assert bolt is not None

    opts, filepath = bolt.render_getopts("jpeg", ".jpg", prj)
    assert filepath.endswith("bolt.jpg")
    assert opts["quality"] == 90
    assert opts["width"] == 128
    assert opts["height"] == 256


def test_jpeg_wrapper_forwards_the_encoder_options():
    """The JPEG-only request fields become PIL's save() keyword arguments."""
    module, raster = _jpeg_wrapper()

    response = module.process(
        "/tmp/shape.jpg",
        {
            "width": 512,
            "height": 512,
            "quality": 90,
            "progressive": True,
            "optimize": True,
            "subsampling": "4:4:4",
            "background": "#ffffff",
        },
    )

    assert response["success"] is True
    path, request, fmt, config_pil = raster.calls[0]
    assert path == "/tmp/shape.jpg"
    assert fmt == "JPEG"
    assert config_pil == {
        "quality": 90,
        "progressive": True,
        "optimize": True,
        "subsampling": "4:4:4",
    }
    # The background is not an encoder option: it is what the image is drawn on.
    assert "background" not in config_pil
    assert request["background"] == "#ffffff"


def test_jpeg_wrapper_omits_unset_options():
    """Options the request does not carry are left to Pillow's own defaults."""
    module, raster = _jpeg_wrapper()

    module.process("/tmp/shape.jpg", {"width": 512, "height": 512, "quality": 70})

    assert raster.calls[0][3] == {"quality": 70}


def _raster_wrapper():
    """Load the shared rasterizer with svglib, reportlab and the SVG step stubbed."""
    svglib_pkg = types.ModuleType("svglib")
    svglib_mod = types.ModuleType("svglib.svglib")
    svglib_pkg.svglib = svglib_mod
    reportlab_pkg = types.ModuleType("reportlab")
    reportlab_graphics = types.ModuleType("reportlab.graphics")
    render_pm = types.ModuleType("reportlab.graphics.renderPM")
    reportlab_pkg.graphics = reportlab_graphics
    reportlab_graphics.renderPM = render_pm

    return _load_wrapper(
        "wrapper_render_raster",
        {
            "wrapper_common": types.ModuleType("wrapper_common"),
            "wrapper_render_svg": types.ModuleType("wrapper_render_svg"),
            "svglib": svglib_pkg,
            "svglib.svglib": svglib_mod,
            "reportlab": reportlab_pkg,
            "reportlab.graphics": reportlab_graphics,
            "reportlab.graphics.renderPM": render_pm,
        },
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 0xFFFFFF),
        ("#ffffff", 0xFFFFFF),
        ("ffffff", 0xFFFFFF),
        ("#000", 0x000000),
        ("#f00", 0xFF0000),
        ("#336699", 0x336699),
        (0x336699, 0x336699),
    ],
)
def test_background_color_is_parsed(value, expected):
    """JPEG has no alpha, so the background is a color the config can choose."""
    assert _raster_wrapper().parse_background(value) == expected


def test_invalid_background_color_is_rejected():
    with pytest.raises(ValueError):
        _raster_wrapper().parse_background("#ff")
