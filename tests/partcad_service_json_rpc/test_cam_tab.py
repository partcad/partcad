#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The Digital Thread's CAM tab and "Extra details" box, as the daemon serves them.

'cam.settings' and 'cam.save', and what 'inspect.object' takes besides a section:
'extra_details', 'detail' and 'cam'. Against a real context of a package written
to a temporary directory; what is shown is caught where it leaves for the IDE
('partcad.viewer.show'), and nothing is made by a machine unless a test says so -
what a print is made of is pinned beside 'partcad.cam_view' and the wrappers.
"""

import pytest

import partcad as pc
import partcad.viewer
from partcad import cam_view
from partcad.shape import Shape
from partcad_service_json_rpc.core import operations
from partcad_service_json_rpc.core.events import EventEmitter
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.rpc.dispatcher import JsonRpcError
from partcad_service_json_rpc.rpc.methods import build_registry

PACKAGE = """\
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


@pytest.fixture
def session(package):
    session = Session(EventEmitter(lambda event, payload: None))
    session.partcad = pc
    session.partcad_ctx = pc.Context(str(package))
    return session


@pytest.fixture
def shown(monkeypatch):
    """What is sent to the IDE, caught on its way: '(tree, how it is shown)' per show."""
    caught = []

    async def show(ctx, tree, **kwargs):
        caught.append((tree, kwargs))
        return True

    monkeypatch.setattr(partcad.viewer, "show", show)
    return caught


@pytest.fixture
def made(monkeypatch):
    """What a part's machine is asked to make, with a stand-in for what it makes: a 20 x 10 x 5 mm block."""
    asked = []

    async def materialize(self, ctx, machine=None, write=False, **kwargs):
        asked.append({"settings": dict(self.config["manufacturing"].get("fff") or {}), "write": write})
        design = await ctx.get_part("//camdemo:block").get_wrapped(ctx)
        made = {"product": dict(design), "stats": {"layers": 25, "volume": 650.0, "solid_volume": 1000.0}}
        if write:
            from partcad.part_factory_manufactured import materialized_path

            path = materialized_path(ctx.get_project(self.project_name), self.config)
            with open(path, "w") as f:
                f.write("materialized")
            made["written"] = path
        return made

    monkeypatch.setattr(Shape, "materialize_async", materialize)
    cam_view.forget_products()
    return asked


def test_both_are_methods_of_the_daemon():
    registry = build_registry()
    assert registry["cam.settings"].__wrapped__ is operations.cam_settings
    assert registry["cam.save"].__wrapped__ is operations.cam_save


def test_the_settings_of_a_print(session):
    answer = operations.cam_settings(session, {"package": "//", "object": "print"})
    assert answer["object"] == "//camdemo:print" and answer["machine"] == "fff"
    infill = next(control for control in answer["controls"] if control["key"] == "infill")
    assert infill["value"] == "20%" and infill["type"] == "fraction"


def test_a_part_no_machine_makes_is_answered_with_why(session):
    answer = operations.cam_settings(session, {"package": "//", "object": "block"})
    assert answer["refused"] and "controls" not in answer
    with pytest.raises(JsonRpcError) as caught:
        operations.cam_settings(session, {"package": "//", "object": "nope"})
    assert "Part //camdemo:nope is not found" in caught.value.message


def test_save_writes_the_declaration(session, package, made):
    answer = operations.cam_save(session, {"package": "//", "object": "print", "settings": {"infill": "35%"}})
    assert answer == {
        "object": "//camdemo:print",
        "config": str(package / "partcad.yaml"),
        "materialized": None,
        "stats": None,
    }
    assert "infill: 35%   # sparse, to see inside" in (package / "partcad.yaml").read_text()
    # Not materialized, so nothing is made again.
    assert made == []
    # And the next request reads what was saved.
    again = operations.cam_settings(session, {"package": "//", "object": "print"})
    assert next(control for control in again["controls"] if control["key"] == "infill")["value"] == "35%"


def test_save_makes_the_materialized_file_again(session, package, made):
    (package / "print.brep").write_text("an old print")

    answer = operations.cam_save(session, {"package": "//", "object": "print", "settings": {"walls": 3}})

    assert answer["materialized"] == str(package / "print.brep")
    assert answer["stats"]["layers"] == 25
    assert (package / "print.brep").read_text() == "materialized"
    # Made with what was saved, as the package now reads.
    assert made == [{"settings": {"infill": "20%", "walls": 3}, "write": True}]


def test_save_refuses_what_the_machine_does_not_take_and_writes_nothing(session, package, made):
    before = (package / "partcad.yaml").read_text()
    for settings in ({"infill": "150%"}, {"diameter": "6"}, {"walls": True}, {"walls": [3]}):
        with pytest.raises(JsonRpcError) as caught:
            operations.cam_save(session, {"package": "//", "object": "print", "settings": settings})
        assert caught.value.code == operations.USAGE_ERROR
    assert (package / "partcad.yaml").read_text() == before
    with pytest.raises(JsonRpcError) as caught:
        operations.cam_save(session, {"package": "//", "object": "block", "settings": {"infill": "30%"}})
    assert "manufacturing method" in caught.value.message


def test_a_part_shows_with_extra_details_unless_asked_otherwise(session, shown):
    operations.inspect_object(session, {"package": "//", "object": "block"})
    operations.inspect_object(session, {"package": "//", "object": "block", "extra_details": False})
    assert [kwargs["extra_details"] for _, kwargs in shown] == [True, False]
    assert all(kwargs["cam"] is None for _, kwargs in shown)


@pytest.mark.parametrize(
    "params, message",
    [
        ({"extra_details": "yes"}, "'extra_details' is true or false"),
        ({"detail": "medium"}, "A level of detail is one of low, high"),
        ({"cam": "fff"}, "'cam' is"),
        ({"cam": {"settings": ["infill"]}}, "'cam: settings' maps"),
        ({"cam": {"settings": {"infill": {"a": 1}}}}, "'cam: settings: infill'"),
        ({"cam": {"machine": 3}}, "'cam: machine'"),
    ],
)
def test_how_a_show_is_drawn_is_checked_before_anything_is_built(session, shown, params, message):
    with pytest.raises(JsonRpcError) as caught:
        operations.inspect_object(session, dict(params, package="//", object="print"))
    assert caught.value.code == operations.USAGE_ERROR
    assert message in caught.value.message
    assert shown == []


def test_the_cam_tab_shows_what_the_machine_makes_with_the_settings_tried(session, shown, made, package):
    answer = operations.inspect_object(
        session, {"package": "//", "object": "print", "cam": {"settings": {"infill": "40%"}}}
    )

    assert answer == {"stats": {"layers": 25, "volume": 650.0, "solid_volume": 1000.0}}
    [(tree, kwargs)] = shown
    assert kwargs["cam"] == {"settings": {"infill": "40%"}}
    assert tree["name"] == "//camdemo:print"
    assert made == [{"settings": {"infill": "40%"}, "write": False}]
    # Tried, not written.
    assert "infill: 20%" in (package / "partcad.yaml").read_text()


def test_the_cam_tab_says_why_a_setting_tried_is_not_one(session, shown, made):
    with pytest.raises(JsonRpcError) as caught:
        operations.inspect_object(session, {"package": "//", "object": "print", "cam": {"settings": {"infill": "x"}}})
    assert caught.value.code == operations.USAGE_ERROR
    assert "infill" in caught.value.message
    assert shown == [] and made == []


def test_only_a_part_a_machine_makes_has_a_cam_drawing(session, shown):
    with pytest.raises(JsonRpcError) as caught:
        operations.inspect_object(session, {"package": "//", "object": "block", "cam": {"settings": {}}})
    assert "manufacturing method" in caught.value.message
    assert shown == []
