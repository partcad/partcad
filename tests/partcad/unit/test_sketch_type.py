#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for package-defined sketchTypes.

A sketchType is the sketch counterpart of a partType: a reusable,
package-defined way to construct sketches. A sketch whose 'type' references it
(':<name>' in its own package, '<package>:<name>' in another) is built by
SketchFactoryWrapper, which shares everything but what it makes of the answer
with PartFactoryWrapper (see 'partcad.type_wrapper'). The tests marked 'slow'
run the scripts in the sandbox.
"""

import asyncio
import os
import textwrap

import pytest

import partcad as pc
from partcad import factory
from partcad.lint.all import get_partcad_schema
from partcad.sketch import Sketch
from partcad.sketch_factory_wrapper import SketchFactoryWrapper

EXAMPLE = "examples/produce_sketch_wrapper"


def _package(path, text):
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "partcad.yaml"), "w") as f:
        f.write(textwrap.dedent(text))


def _script(path, name, text):
    with open(os.path.join(path, name), "w") as f:
        f.write(textwrap.dedent(text))


def test_the_wrapper_factory_is_registered_for_sketches():
    assert factory.all["sketch"]["wrapper"] is SketchFactoryWrapper


def test_a_sketch_type_is_enumerated_and_is_not_a_sketch():
    ctx = pc.Context(EXAMPLE)
    root = ctx.get_project(ctx.get_current_project_path())
    cfg = root.get_sketch_type_config("plate")
    assert cfg is not None
    assert cfg.get("kind", "wrapper") == "wrapper"
    assert cfg.get("path") == "plate.py"
    assert "plate" in root.object_names("sketchType")
    # A sketchType keeps a namespace of its own, as a partType does: the
    # example names a sketch after its type.
    assert root.get_part_type_config("plate") is None


def test_the_short_type_is_expanded_and_stored():
    ctx = pc.Context(EXAMPLE)
    root = ctx.get_project(ctx.get_current_project_path())
    sketch = ctx.get_sketch(":plate")
    assert isinstance(sketch, Sketch)
    assert root.get_sketch_config("plate")["type"] == root.name + ":plate"


def test_an_unknown_sketch_type_is_not_found():
    ctx = pc.Context(EXAMPLE)
    root = ctx.get_project(ctx.get_current_project_path())
    assert root.get_sketch_type_config("nope") is None


def test_a_sketch_type_takes_no_layer_parameters():
    """'include' and 'exclude' are a drawing's; a script has no layers to filter."""
    assert factory.accepted_object_type_parameters("sketch", "pkg:plate") == {}


def test_a_sketch_type_with_an_extension_reads_the_sketch_s_file(tmp_path):
    _package(
        tmp_path,
        """
        sketchTypes:
          outline:
            path: read_outline.py
            extension: outline
        sketches:
          default:
            type: ":outline"
          named:
            type: ":outline"
            path: files/other.outline
        """,
    )
    ctx = pc.Context(str(tmp_path))
    default = ctx.get_sketch(":default")
    assert default.path == str(tmp_path / "default.outline")
    assert default.path in default.cache_dependencies
    assert ctx.get_sketch(":named").path == str(tmp_path / "files" / "other.outline")


def test_a_sketch_type_without_an_extension_reads_no_file():
    ctx = pc.Context(EXAMPLE)
    assert getattr(ctx.get_sketch(":plate"), "path", None) is None


def test_a_sketch_type_of_another_package_keys_on_its_image(tmp_path):
    _package(
        tmp_path / "reader",
        """
        sketchTypes:
          outline:
            path: read_outline.py
            dockerImage: ghcr.io/partcad/partcad-test-outline-reader:1
        """,
    )
    _package(
        tmp_path / "consumer",
        """
        dependencies:
          reader:
            type: local
            path: ../reader
        sketches:
          profile:
            type: reader:outline
        """,
    )
    ctx = pc.Context(str(tmp_path / "consumer"))
    sketch = ctx.get_sketch(":profile")
    assert sketch.config["type"] == "reader:outline"
    assert sketch.environment_cache_key.endswith(";image=ghcr.io/partcad/partcad-test-outline-reader:1")


# --------------------------------------------------------------------------- #
# The schema                                                                  #
# --------------------------------------------------------------------------- #


def test_the_schema_accepts_a_sketch_type_and_a_sketch_of_it():
    import jsonschema
    import yaml

    schema = get_partcad_schema()
    with open(os.path.join(EXAMPLE, "partcad.yaml")) as f:
        config = yaml.safe_load(f)
    jsonschema.validate(config, schema)
    jsonschema.validate({"sketches": {"s": {"type": "other:outline", "path": "s.outline", "anything": 1}}}, schema)


def test_the_schema_refuses_require_solid_on_a_sketch_type():
    import jsonschema

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"sketchTypes": {"t": {"path": "t.py", "requireSolid": True}}}, get_partcad_schema())


# --------------------------------------------------------------------------- #
# In the sandbox                                                              #
# --------------------------------------------------------------------------- #


def _build(ctx, name):
    # Not skipped when it raises: a sketch type's failure is reported against
    # the sketch and answered with None, so an exception here is a regression.
    sketch = ctx.get_sketch(name)
    assert sketch is not None
    return sketch, asyncio.run(sketch.get_wrapped(ctx))


@pytest.mark.slow
def test_the_example_builds_a_face_with_holes_and_an_open_wire():
    ctx = pc.Context(EXAMPLE)
    sketch, wrapped = _build(ctx, ":plate")
    assert wrapped is not None
    # The plate, and the bend line beside it, each one component.
    assert len(sketch.components) == 2
    bbox = asyncio.run(sketch.get_bounding_box_async(ctx))
    assert bbox[0] == pytest.approx(-20) and bbox[3] == pytest.approx(20)
    assert bbox[2] == pytest.approx(0) and bbox[5] == pytest.approx(0)
    # Each sketch sets the parameters to its own values.
    wide, _ = _build(ctx, ":plate_wide")
    assert asyncio.run(wide.get_bounding_box_async(ctx))[3] == pytest.approx(35)


@pytest.mark.slow
def test_a_file_backed_sketch_type_of_another_package_reads_the_sketch_s_file(tmp_path):
    reader = tmp_path / "reader"
    _package(
        reader,
        """
        sketchTypes:
          outline:
            path: read_outline.py
            extension: outline
        """,
    )
    _script(
        reader,
        "read_outline.py",
        """
        if __name__ == "__partcad_sketch__":
            from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
            from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt

            width, height, radius = (float(v) for v in open(request["path"]).read().split())

            def polygon(points):
                maker = BRepBuilderAPI_MakeWire()
                for a, b in zip(points, points[1:] + points[:1]):
                    maker.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*a, 0), gp_Pnt(*b, 0)).Edge())
                return maker.Wire()

            outer = polygon([(0, 0), (width, 0), (width, height), (0, height)])
            circle = gp_Circ(gp_Ax2(gp_Pnt(width / 2, height / 2, 0), gp_Dir(0, 0, -1)), radius)
            hole = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circle).Edge()).Wire()
            maker = BRepBuilderAPI_MakeFace(outer, True)
            maker.Add(hole)
            output = {"shape": maker.Face()}
        """,
    )
    consumer = tmp_path / "consumer"
    _package(
        consumer,
        """
        dependencies:
          reader:
            type: local
            path: ../reader
        sketches:
          profile:
            type: reader:outline
        parts:
          slab:
            type: extrude
            sketch: profile
            depth: 2
        """,
    )
    (consumer / "profile.outline").write_text("30 10 2\n")
    ctx = pc.Context(str(consumer))
    sketch, wrapped = _build(ctx, ":profile")
    assert wrapped is not None
    assert asyncio.run(sketch.get_bounding_box_async(ctx)) == pytest.approx((0, 0, 0, 30, 10, 0))
    # And a part built from it is the solid with the hole through it.
    slab = ctx.get_part(":slab")
    assert asyncio.run(slab.get_bounding_box_async(ctx)) == pytest.approx((0, 0, 0, 30, 10, 2))


@pytest.mark.slow
@pytest.mark.parametrize(
    "body, message",
    [
        ('from build123d import Box\n    output = {"shape": Box(1, 1, 1)}', "handed back a solid"),
        ("output = {}", "no edge, wire or face"),
        ('output = {"shapes": [[]]}', "no edge, wire or face"),
        ('output = {"shapes": [[None]]}', "no edge, wire or face"),
        ('output = {"exception": "the outline is malformed"}', "the outline is malformed"),
    ],
)
def test_a_sketch_type_s_script_that_hands_back_no_sketch_fails_the_sketch(tmp_path, body, message):
    _package(
        tmp_path,
        """
        sketchTypes:
          broken:
            path: broken.py
        sketches:
          s:
            type: ":broken"
        """,
    )
    _script(tmp_path, "broken.py", 'if __name__ == "__partcad_sketch__":\n    %s\n' % body)
    ctx = pc.Context(str(tmp_path))
    sketch, wrapped = _build(ctx, ":s")
    assert wrapped is None
    assert any(message in str(e) for e in sketch.errors), sketch.errors


def test_a_sketch_type_s_script_outside_its_package_is_refused(tmp_path):
    _package(
        tmp_path / "pkg",
        """
        sketchTypes:
          escape:
            path: ../outside.py
        sketches:
          s:
            type: ":escape"
        """,
    )
    (tmp_path / "outside.py").write_text("raise SystemExit('never run')\n")
    ctx = pc.Context(str(tmp_path / "pkg"))
    sketch = ctx.get_sketch(":s")
    assert asyncio.run(sketch.get_wrapped(ctx)) is None
    assert any("outside its package" in str(e) for e in sketch.errors), sketch.errors


def test_a_sketch_type_s_script_through_a_link_out_of_its_package_is_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "escape.py").write_text("raise SystemExit('never run')\n")
    _package(
        tmp_path / "pkg",
        """
        sketchTypes:
          escape:
            path: linked/escape.py
        sketches:
          s:
            type: ":escape"
        """,
    )
    try:
        os.symlink(str(outside), str(tmp_path / "pkg" / "linked"), target_is_directory=True)
    except (OSError, NotImplementedError) as e:  # Windows without the privilege to link
        pytest.skip("Cannot create a symbolic link here: %s" % e)
    ctx = pc.Context(str(tmp_path / "pkg"))
    sketch = ctx.get_sketch(":s")
    assert asyncio.run(sketch.get_wrapped(ctx)) is None
    assert any("outside its package" in str(e) for e in sketch.errors), sketch.errors


def test_a_sketch_type_s_script_outside_its_package_is_not_read_for_its_version(tmp_path, monkeypatch):
    """The key reads a script's 'CACHE_VERSION'; one outside the package is not read at all."""
    from partcad import code_version

    _package(
        tmp_path / "pkg",
        """
        sketchTypes:
          escape:
            path: ../outside.py
        sketches:
          s:
            type: ":escape"
        """,
    )
    (tmp_path / "outside.py").write_text("CACHE_VERSION = 7\n")
    read = []
    monkeypatch.setattr(code_version, "declared", lambda path: read.append(path) or 0)
    ctx = pc.Context(str(tmp_path / "pkg"))
    sketch = ctx.get_sketch(":s")
    assert asyncio.run(sketch.get_wrapped(ctx)) is None
    assert not any("outside.py" in str(p) for p in read), read
