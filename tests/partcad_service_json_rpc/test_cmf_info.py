#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'cmf.info': what the IDE's CMF tab is drawn from (docs/design/cmf.md, section 9).

Against a real context of a package written to a temporary directory, with
nothing built: a declaration needs no geometry, and the parts' builds are
stood in for. What each row says is pinned beside 'partcad.cmf' in
'tests/partcad/unit/test_cmf_ide.py'; what is pinned here is the method -- which
kinds it answers about, how it is told one from another, and what it refuses.
"""

import pytest
import yaml

import partcad as pc
from partcad import shape_envelope
from partcad.part import Part
from partcad_service_json_rpc.core import operations
from partcad_service_json_rpc.core.events import EventEmitter
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.rpc.dispatcher import JsonRpcError
from partcad_service_json_rpc.rpc.methods import build_registry


@pytest.fixture
def session(tmp_path, monkeypatch):
    config = {
        "name": "//cmf",
        "colors": {"red": {"display": "#C91A09"}, "a;b": {"display": "#123456"}},
        "materials": {"alu": {"density": 2700}},
        "finishes": {"satin": {"display": {"roughness": 0.6}}},
        "parts": {
            "box": {
                "type": "stl",
                "path": "box.stl",
                "parameters": {"color": {"type": "string", "default": ":red"}},
            }
        },
        "sketches": {"outline": {"type": "basic", "rectangle": {"x": 1, "y": 1}}},
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    (tmp_path / "box.stl").write_text("solid box\nendsolid box\n")

    async def get_wrapped(self, ctx):
        # Built, and recording nothing: what the tab says is then what the
        # part declares.
        self._metadata = {}
        return object()

    monkeypatch.setattr(Part, "get_wrapped", get_wrapped)
    session = Session(EventEmitter(lambda event, payload: None))
    session.partcad = pc
    session.partcad_ctx = pc.Context(str(tmp_path))
    return session


def test_it_is_a_method_of_the_daemon():
    assert build_registry()["cmf.info"].__wrapped__ is operations.cmf_info


@pytest.mark.parametrize("kind, name", [("color", "red"), ("material", "alu"), ("finish", "satin")])
def test_a_declaration_is_asked_about_by_its_kind(session, kind, name):
    answer = operations.cmf_info(session, {"package": "//cmf", "object": name, "kind": kind})

    assert answer["object"] == "//cmf:" + name
    assert answer["kind"] == kind
    assert answer["declaration"]["reference"] == "//cmf:" + name


def test_a_part_is_its_one_item(session):
    answer = operations.cmf_info(session, {"package": "//cmf", "object": "box", "kind": "part"})

    assert answer["kind"] == "part"
    ((item,),) = [answer["items"]]
    assert item["name"] == "//cmf:box"
    assert item["cmf"]["sets"][0]["color"] == "//cmf:red"


def test_a_part_is_found_without_being_told_what_it_is(session):
    answer = operations.cmf_info(session, {"package": "//cmf", "object": "box"})

    assert answer["kind"] == "part"


def test_a_declaration_that_is_not_there_is_refused_by_name(session):
    with pytest.raises(JsonRpcError) as refused:
        operations.cmf_info(session, {"package": "//cmf", "object": "blue", "kind": "color"})

    assert "//cmf:blue" in str(refused.value)


def test_a_declaration_named_with_a_reserved_character_is_found_as_the_explorer_lists_it(session):
    """The explorer sends a key as it is written: 'a;b' is that colour, not 'a' with a parameter 'b'."""
    for name in ("a;b", "a%3Bb"):
        answer = operations.cmf_info(session, {"package": "//cmf", "object": name, "kind": "color"})
        assert answer["declaration"]["display"].startswith("#123456")


def test_a_sketch_is_made_of_nothing_and_is_refused(session):
    with pytest.raises(JsonRpcError) as refused:
        operations.cmf_info(session, {"package": "//cmf", "object": "outline", "kind": "sketch"})

    assert "'sketch'" in str(refused.value)


def test_nothing_is_recorded_for_a_declaration(session):
    # A declaration is no shape, and asking about one builds nothing.
    operations.cmf_info(session, {"package": "//cmf", "object": "red", "kind": "color"})

    part = session.partcad_ctx.get_part("//cmf:box")
    assert shape_envelope.METADATA_CMF not in (part._metadata or {})
