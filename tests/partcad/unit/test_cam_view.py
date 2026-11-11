#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the Digital Thread draws of an object, and its CAM tab ('partcad.cam_view').

The "Extra details" box - visuals or the object as it is, the preview's level of
detail or the finer one, and the exception a part a machine makes is - and the
CAM tab's half: which settings a machine takes, read off the schema; trying them
without writing; and saving them into a 'partcad.yaml' the way its author wrote
it.
"""

import asyncio
import types

import pytest

import partcad as pc
from partcad import cam as pc_cam
from partcad import cam_view, shape_envelope, shape_gltf
from partcad.shape import Shape

#
# The level of detail
#


def test_a_level_of_detail_is_low_or_high():
    assert shape_gltf.detail_of(None) == shape_gltf.DETAIL_LOW
    assert shape_gltf.detail_of("high") == shape_gltf.DETAIL_HIGH
    with pytest.raises(ValueError, match="low, high"):
        shape_gltf.detail_of("medium")


def _tree(size):
    measurements = {shape_envelope.METADATA_BBOX: [0, 0, 0, size, size, size]}
    return {"name": "x", shape_envelope.KEY_METADATA: {shape_envelope.METADATA_MEASUREMENTS: measurements}}


@pytest.mark.parametrize("size", [5.0, 100.0, 5000.0])
def test_the_high_level_is_finer_on_both_counts(size):
    low = shape_gltf.tolerance_for(_tree(size), shape_gltf.DETAIL_LOW)
    high = shape_gltf.tolerance_for(_tree(size), shape_gltf.DETAIL_HIGH)
    assert high < low
    # The low level is what a preview always was.
    assert low == shape_gltf.tolerance_for(_tree(size))
    assert shape_gltf.angular_tolerance_for() == shape_gltf.DEFAULT_ANGULAR_TOLERANCE
    assert shape_gltf.angular_tolerance_for("high") < shape_gltf.angular_tolerance_for("low")


#
# What the 3D view draws
#


def _shape(kind, manufacturing=None):
    config = {"name": "thing"}
    if manufacturing is not None:
        config["manufacturing"] = manufacturing
    return types.SimpleNamespace(kind=kind, config=config, get_final_config=lambda: config)


PRINT = {"method": "additive", "source": "design"}


def test_a_part_or_a_sketch_starts_out_drawn_as_it_is_and_finely():
    for kind in ("part", "sketch"):
        drawn = cam_view.representation(_shape(kind))
        assert drawn == cam_view.Representation(extra_details=True, visuals=False, detail="high", stripped=False)


def test_anything_else_starts_out_drawn_as_its_visuals_at_the_previews_level():
    for kind in ("assembly", "scene", None):
        drawn = cam_view.representation(_shape(kind))
        assert drawn == cam_view.Representation(extra_details=False, visuals=True, detail="low", stripped=False)


def test_the_box_says_which():
    assert cam_view.representation(_shape("part"), extra_details=False).visuals is True
    assert cam_view.representation(_shape("part"), extra_details=False).detail == "low"
    assert cam_view.representation(_shape("assembly"), extra_details=True).detail == "high"
    assert cam_view.representation(_shape("assembly"), extra_details=True).visuals is False
    # A level asked for outranks the box.
    assert cam_view.representation(_shape("assembly"), detail="high").detail == "high"


def test_a_part_a_machine_makes_is_drawn_as_it_is_made_at_the_previews_level():
    printed = _shape("part", PRINT)
    assert cam_view.made_by_machine(printed)
    drawn = cam_view.representation(printed)
    assert drawn == cam_view.Representation(extra_details=True, visuals=False, detail="low", stripped=True)
    # Cleared, it is drawn as its design, as it always was.
    cleared = cam_view.representation(printed, extra_details=False)
    assert cleared == cam_view.Representation(extra_details=False, visuals=True, detail="low", stripped=False)
    # Its CAM tab draws what its machine makes, finely.
    cam = cam_view.representation(printed, cam=True)
    assert cam == cam_view.Representation(extra_details=True, visuals=False, detail="high", stripped=True)


@pytest.mark.parametrize("method", ["subtractive", "forming"])
def test_a_cut_or_molded_part_is_drawn_as_finely_as_the_box_says(method):
    """What a router or a mold makes has curved faces -- a drilled hole, a molded knob -- as any part does."""
    made = _shape("part", {"method": method, "source": "stock"})
    assert cam_view.made_by_machine(made)
    # And it is a solid, not a print's prisms: no face of it is left out, so
    # none loses the colour it was given.
    ticked = cam_view.representation(made)
    assert ticked == cam_view.Representation(extra_details=True, visuals=False, detail="high", stripped=False)
    cleared = cam_view.representation(made, extra_details=False)
    assert cleared == cam_view.Representation(extra_details=False, visuals=True, detail="low", stripped=False)
    assert cam_view.representation(made, cam=True) == cam_view.Representation(
        extra_details=True, visuals=False, detail="high", stripped=False
    )


def test_only_a_part_made_by_following_a_route_is_made_by_a_machine():
    assert not cam_view.made_by_machine(_shape("part"))
    assert not cam_view.made_by_machine(_shape("part", {"method": "sheet_metal"}))
    assert not cam_view.made_by_machine(_shape("assembly", PRINT))
    for method in ("additive", "subtractive", "forming"):
        assert cam_view.made_by_machine(_shape("part", {"method": method}))


#
# The settings a machine takes
#


def test_a_printer_takes_its_schemas_settings():
    controls = {control["key"]: control for control in cam_view.machine_controls("fff")}
    for key in (
        "toolAxis",
        "nozzle",
        "filament",
        "layerHeight",
        "lineWidth",
        "walls",
        "topLayers",
        "bottomLayers",
        "infill",
        "infillPattern",
        "feed",
    ):
        assert key in controls, key
    # The second spelling of the axis, who writes the route and a description are no settings.
    assert not {"along", "implementation", "desc"} & set(controls)
    assert controls["toolAxis"]["type"] == "axis" and "-Y" in controls["toolAxis"]["choices"]
    assert controls["infill"]["type"] == "fraction"
    assert controls["walls"]["type"] == "count" and controls["walls"]["minimum"] == 0
    assert controls["layerHeight"]["type"] == "length"
    assert controls["feed"]["type"] == "feed"
    assert controls["infillPattern"]["type"] == "text"
    assert "layer" in controls["layerHeight"]["description"]


def test_every_machine_has_its_own():
    assert [control["key"] for control in cam_view.machine_controls("mold")] == ["shrinkage"]
    assert cam_view.machine_controls("mold")[0]["type"] == "fraction"
    cnc = {control["key"]: control for control in cam_view.machine_controls("cnc")}
    assert cnc["operation"]["type"] == "choice" and cnc["operation"]["choices"] == ["profile", "pocket", "engrave"]
    assert "kerf" in {control["key"] for control in cam_view.machine_controls("laser")}
    # A saw's cuts are a list, not a setting.
    assert "cuts" not in {control["key"] for control in cam_view.machine_controls("cut")}


def test_settings_tried_are_written_over_a_copy_of_the_declaration():
    config = {"name": "p", "manufacturing": {"method": "additive", "fff": {"infill": "20%", "along": "-Y"}}}
    tried = cam_view.with_settings(config, "fff", {"infill": "40%", "walls": 3, "toolAxis": "-X"})
    assert tried["manufacturing"]["fff"] == {"infill": "40%", "walls": 3, "toolAxis": "-X"}
    assert config["manufacturing"]["fff"] == {"infill": "20%", "along": "-Y"}
    taken = cam_view.with_settings(config, "fff", {"infill": None})
    assert taken["manufacturing"]["fff"] == {"along": "-Y"}


@pytest.mark.parametrize(
    "typed, written",
    [("3", 3), ("0.2", 0.2), (" 20% ", "20%"), ("0.2 mm", "0.2 mm"), ("1e3", 1000.0), (4, 4), ("-Y", "-Y")],
)
def test_a_setting_is_written_as_a_number_where_it_is_one(typed, written):
    assert cam_view.written_value(typed) == written
    assert type(cam_view.written_value(typed)) is type(written)


#
# On a package
#

PACKAGE = """\
# A design, and a print of it.
name: //camdemo

parts:
  block:
    type: basic
    cuboid: [20, 10, 5]
  print:
    desc: The block, printed
    manufacturing:
      method: additive
      source: block
      fff:
        infill: 20%   # sparse, to see inside
"""


@pytest.fixture
def package(tmp_path):
    (tmp_path / "partcad.yaml").write_text(PACKAGE)
    return tmp_path


def test_the_cam_tab_says_how_a_print_is_made_and_with_what(package):
    ctx = pc.Context(str(package))
    part = ctx.get_part("//camdemo:print")

    settings = cam_view.settings(ctx, part)

    assert settings["method"] == "additive" and settings["machine"] == "fff" and settings["design"] == "block"
    assert settings["description"] == "The block, printed"
    controls = {control["key"]: control for control in settings["controls"]}
    assert controls["infill"]["value"] == "20%" and controls["infill"]["default"] == 0.15
    assert controls["walls"]["value"] is None and controls["walls"]["default"] == 2
    assert settings["materialized"] == {"path": "print.brep", "exists": False}
    assert "refused" not in settings


def test_a_part_no_machine_makes_has_no_cam_tab(package):
    ctx = pc.Context(str(package))
    settings = cam_view.settings(ctx, ctx.get_part("//camdemo:block"))
    assert "manufacturing method" in settings["refused"] and "controls" not in settings


def test_saving_writes_the_settings_and_keeps_the_rest_of_the_file(package):
    ctx = pc.Context(str(package))
    part = ctx.get_part("//camdemo:print")

    written = cam_view.save_settings(ctx, part, values={"infill": "30%", "walls": "3", "topLayers": ""})

    assert written == str(package / "partcad.yaml")
    text = (package / "partcad.yaml").read_text()
    assert "# A design, and a print of it." in text
    assert "infill: 30%   # sparse, to see inside" in text
    assert "walls: 3\n" in text and "topLayers" not in text
    # As PartCAD reads it again.
    again = pc.Context(str(package)).get_part("//camdemo:print")
    assert cam_view.settings(ctx, again)["controls"][5]["key"] == "walls"
    assert {c["key"]: c["value"] for c in cam_view.settings(ctx, again)["controls"]}["walls"] == 3


def test_a_setting_the_machine_does_not_take_is_refused_and_nothing_is_written(package):
    ctx = pc.Context(str(package))
    part = ctx.get_part("//camdemo:print")
    before = (package / "partcad.yaml").read_text()
    with pytest.raises(pc_cam.CamConfigError, match="infill"):
        cam_view.save_settings(ctx, part, values={"infill": "150%"})
    with pytest.raises(pc_cam.CamConfigError, match="diameter"):
        cam_view.save_settings(ctx, part, values={"diameter": "6"})
    assert (package / "partcad.yaml").read_text() == before


def test_a_part_another_file_declares_has_nowhere_to_be_written(package):
    ctx = pc.Context(str(package))
    project = ctx.get_project("//camdemo")
    with pytest.raises(ValueError, match="not declared"):
        project.set_machine_settings("elsewhere", "fff", {"infill": "30%"})


def test_saving_nothing_new_names_no_machine(package):
    (package / "partcad.yaml").write_text(
        PACKAGE.replace("      fff:\n        infill: 20%   # sparse, to see inside\n", "")
    )
    ctx = pc.Context(str(package))
    ctx.get_project("//camdemo").set_machine_settings("print", "fff", {"infill": None})
    assert "fff" not in (package / "partcad.yaml").read_text()


def test_settings_tried_make_the_part_again_once_each(package, monkeypatch):
    made = []

    async def materialize(self, ctx, machine=None, **kwargs):
        made.append((self.config["manufacturing"].get("fff"), machine))
        return {"product": {"brep": b"product"}, "stats": {"layers": 25}}

    monkeypatch.setattr(Shape, "materialize_async", materialize)
    cam_view.forget_products()
    ctx = pc.Context(str(package))
    part = ctx.get_part("//camdemo:print")

    first = asyncio.run(cam_view.product_async(ctx, part, values={"infill": "40%"}))
    again = asyncio.run(cam_view.product_async(ctx, part, values={"infill": "40%"}))
    asyncio.run(cam_view.product_async(ctx, part))

    assert first is again
    assert made == [({"infill": "40%"}, "fff"), ({"infill": "20%"}, None)]
    # The part itself states what it states.
    assert part.config["manufacturing"]["fff"] == {"infill": "20%"}
    with pytest.raises(pc_cam.CamConfigError, match="infill"):
        asyncio.run(cam_view.product_async(ctx, part, values={"infill": "two"}))
    assert len(made) == 2


def test_a_product_is_made_again_when_the_design_it_is_made_after_changes(tmp_path, monkeypatch):
    """A part with a geometry of its own keeps its key when its design is edited; what it makes does not."""
    made = []

    async def materialize(self, ctx, machine=None, **kwargs):
        design = ctx.get_part("//camdemo:block").config["cuboid"]
        made.append(design)
        return {"product": {"brep": ("made after %s" % design).encode()}, "stats": {}}

    monkeypatch.setattr(Shape, "materialize_async", materialize)
    cam_view.forget_products()

    def product(width):
        root = tmp_path / str(width)
        root.mkdir()
        (root / "partcad.yaml").write_text(
            PACKAGE.replace("cuboid: [20, 10, 5]", "cuboid: [%d, 10, 5]" % width)
            # The print, scanned: a geometry of its own, the same in both.
            .replace("    desc: The block, printed\n", "    type: basic\n    cuboid: [19, 9, 4]\n")
        )
        ctx = pc.Context(str(root))
        return asyncio.run(cam_view.product_async(ctx, ctx.get_part("//camdemo:print")))

    assert product(20)["product"]["brep"] == b"made after [20, 10, 5]"
    assert product(30)["product"]["brep"] == b"made after [30, 10, 5]"
    assert made == [[20, 10, 5], [30, 10, 5]]


def test_the_product_is_drawn_as_the_part(package):
    ctx = pc.Context(str(package))
    part = ctx.get_part("//camdemo:print")
    node = cam_view.product_tree(ctx, part, {"product": {"brep": b"x", "metadata": {}}})
    assert node["name"] == "//camdemo:print" and node["label"] == "print"
    assert node[shape_envelope.KEY_KIND] == "part"
