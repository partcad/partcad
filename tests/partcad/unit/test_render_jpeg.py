#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for rendering 2D projections to JPEG.

JPEG shares the whole rasterization path with PNG (see
'builtin/render/render_raster.py'); what is specific to it is the file
extension, the encoder options and the background the transparent projection is
flattened onto. These tests cover that without the sandbox: an end-to-end render
is exercised by 'test_render.test_render_project' (the 'feature_render' example
renders JPEG) and by 'features/render.feature'.
"""

import importlib.util
import os
import sys
import types

import pytest

import partcad as pc
from partcad import output
from partcad.shape import PART_EXTENSION_MAPPING, RENDER_EXTENSION_MAPPING, SERIALIZED_PART_TYPES

RENDER_DIR = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.RENDER]]


def _load_implementation(name, stubs):
    """Import a built-in render implementation by path, with its imports stubbed.

    The implementations run inside a render sandbox that has svglib, reportlab
    and the CAD stack installed; the environment running these tests has none of
    them, so the modules they import are replaced by recorders.
    """
    saved = {key: sys.modules.get(key) for key in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location("test_%s" % name, os.path.join(RENDER_DIR, "%s.py" % name))
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
    """A stand-in for 'render_raster' that records how it was called."""
    stub = types.ModuleType("render_raster")
    stub.calls = []

    def process(path, request, fmt, config_pil=None):
        stub.calls.append((path, request, fmt, config_pil))
        return {"success": True, "exception": None}

    stub.process = process
    return stub


def _jpeg_implementation():
    raster = _raster_stub()
    module = _load_implementation(
        "render_jpeg",
        {"wrapper_common": types.ModuleType("wrapper_common"), "render_raster": raster},
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


def test_the_builtin_jpeg_declares_the_jpg_extension():
    """'//builtin/render' is where the '.jpg' now comes from."""
    ctx = pc.init("examples")
    declared = output.builtin_formats(ctx, output.RENDER)["jpeg"]
    assert declared["extension"] == "jpg"


def test_jpeg_output_getopts_uses_the_jpg_extension():
    """A package's JPEG render options resolve to a '<name>.jpg' output path.

    'feature_render' is the example that configures the render targets; the
    'prefix' it gives the raster ones is part of the resolved path.
    """
    ctx = pc.init("examples")
    prj = ctx.get_project("//feature_render")
    cube = prj.get_part("cube")
    assert cube is not None

    impl, filepath = cube.output_getopts(ctx, "jpeg", prj)
    assert filepath.endswith(os.path.join("images", "cube.jpg"))
    assert impl.section == output.RENDER
    assert impl.parameters["quality"] == 90
    assert impl.parameters["width"] == 256
    assert impl.parameters["height"] == 192


def test_jpeg_implementation_forwards_the_encoder_options():
    """The JPEG-only request fields become PIL's save() keyword arguments."""
    module, raster = _jpeg_implementation()

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


def test_jpeg_implementation_omits_unset_options():
    """Options the request does not carry are left to Pillow's own defaults."""
    module, raster = _jpeg_implementation()

    module.process("/tmp/shape.jpg", {"width": 512, "height": 512, "quality": 70})

    assert raster.calls[0][3] == {"quality": 70}


def test_png_keeps_its_transparent_background():
    """PNG has an alpha channel, so it does not flatten onto a color."""
    raster = _raster_stub()
    module = _load_implementation(
        "render_png",
        {"wrapper_common": types.ModuleType("wrapper_common"), "render_raster": raster},
    )
    module.process("/tmp/shape.png", {"width": 512, "height": 512})
    assert raster.calls[0][2] == "PNG"
    assert raster.calls[0][3] == {"transparent": True}


def _raster_implementation():
    """Load the shared rasterizer with svglib, reportlab and the SVG step stubbed."""
    svglib_pkg = types.ModuleType("svglib")
    svglib_mod = types.ModuleType("svglib.svglib")
    svglib_pkg.svglib = svglib_mod
    reportlab_pkg = types.ModuleType("reportlab")
    reportlab_graphics = types.ModuleType("reportlab.graphics")
    render_pm = types.ModuleType("reportlab.graphics.renderPM")
    reportlab_pkg.graphics = reportlab_graphics
    reportlab_graphics.renderPM = render_pm

    return _load_implementation(
        "render_raster",
        {
            "wrapper_common": types.ModuleType("wrapper_common"),
            "render_svg": types.ModuleType("render_svg"),
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
    assert _raster_implementation().parse_background(value) == expected


def test_invalid_background_color_is_rejected():
    with pytest.raises(ValueError):
        _raster_implementation().parse_background("#ff")


def _readme_text(tmp_path):
    """The generated README, with path separators normalized.

    The generator builds the image 'src' with 'os.path.join', so on Windows it
    comes back as '.\\./images\\bolt.jpg'. That is pre-existing behaviour shared
    by every image format; these tests are about which file is referenced, not
    about the separator.
    """
    return (tmp_path / "README.md").read_text().replace("\\", "/")


def _readme_project(tmp_path, package_render, part_render):
    """A throwaway package whose only part carries its own render options."""
    (tmp_path / "bolt.step").write_bytes(b"")
    (tmp_path / "partcad.yaml").write_text(
        "parts:\n"
        "  bolt:\n"
        "    type: step\n"
        "    path: bolt.step\n"
        "%s"
        "render:\n"
        "%s" % (part_render, package_render)
    )
    ctx = pc.Context(str(tmp_path))
    return ctx.get_project("//")


def test_readme_preview_follows_a_shape_only_render_config(tmp_path):
    """A format enabled on the shape alone still gets its README preview.

    'render_async()' merges the shape's own 'render' section over the package's
    when it decides what to render, so a shape-only 'jpeg' section does produce
    a '.jpg'. The README generator has to apply the same merge or it looks for a
    file that was never rendered (and misses the shape's 'prefix' override).
    """
    prj = _readme_project(
        tmp_path,
        package_render="  readme: README.md\n",
        part_render="    render:\n      jpeg:\n        prefix: ./images\n",
    )
    images = tmp_path / "images"
    images.mkdir()
    (images / "bolt.jpg").write_bytes(b"")

    prj.render_readme_async(prj.config_obj.get("render", {}), None)

    assert "images/bolt.jpg" in _readme_text(tmp_path)


def test_readme_preview_honors_a_format_enabled_without_options(tmp_path):
    """A bare 'png:' key means "render it with the defaults", not "skip it".

    The same idiom the examples use for 'readme:'. The preview has to be emitted
    for it, since that is exactly what '_should_render_format()' renders.
    """
    prj = _readme_project(tmp_path, package_render="  readme: README.md\n  png:\n", part_render="")
    (tmp_path / "bolt.png").write_bytes(b"")

    prj.render_readme_async(prj.config_obj.get("render", {}), None)

    assert "bolt.png" in _readme_text(tmp_path)
