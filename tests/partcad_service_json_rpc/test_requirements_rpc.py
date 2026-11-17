#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'requirements.add' and 'requirements.remove' -- 'pc req add' and 'pc req remove' -- as the daemon serves them.

Against a real context of a package written to a temporary directory, and read
back off the file: what is pinned is what lands in 'partcad.yaml', that the rest
of the file is left as it was written, and that what PartCAD then reads is the
requirement asked for. What each kind of requirement means is pinned beside
'partcad.requirements'; how each is written, beside 'partcad.requirements_edit'.
"""

import pytest
import yaml

import partcad as pc
from partcad_service_json_rpc.core import operations
from partcad_service_json_rpc.core.events import EventEmitter
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.rpc.dispatcher import JsonRpcError
from partcad_service_json_rpc.rpc.methods import build_registry

PACKAGE = """\
name: //reqdemo

interfaces:
  mount:
    desc: Where it is screwed down

parts:
  # What was here before anything was required of it.
  bracket:
    type: basic
    cuboid: [20, 10, 5]
    qual:
      sim:
        drop:
          path: sim:sim
          feature: holds
    requirements:
      features:
        holds: Holds a shelf
  old-bracket:
    type: basic
    cuboid: [20, 10, 6]
  copy:
    type: alias
    source: bracket
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


def _written(package) -> dict:
    return yaml.safe_load((package / "partcad.yaml").read_text())["parts"]


def _requirements(package, name="bracket"):
    return _written(package)[name].get("requirements")


def _add(session, **params):
    session.partcad_ctx = pc.Context(session.partcad_ctx.root_path)
    return operations.requirements_add(session, {"package": "//reqdemo", "object": "bracket", **params})


def _remove(session, **params):
    session.partcad_ctx = pc.Context(session.partcad_ctx.root_path)
    return operations.requirements_remove(session, {"package": "//reqdemo", "object": "bracket", **params})


def test_both_are_daemon_methods():
    registry = build_registry()
    assert registry["requirements.add"].__wrapped__ is operations.requirements_add
    assert registry["requirements.remove"].__wrapped__ is operations.requirements_remove


def test_each_kind_is_written_where_partcad_reads_it(session, package):
    _add(session, requirement="physics", name="mass", value=">0,<=0.05")
    _add(session, requirement="port", name="top", value={"direction": [0, 0, -1]})
    _add(session, requirement="interface", name="mount", instances=["left", "right"])
    _add(session, requirement="match", name=":old-bracket", value={"weight": 5})
    _add(session, requirement="has", name="private_dependencies", value=False)
    _add(session, requirement="feature", name="fits", value="Fits a 20 mm slot")

    assert _requirements(package) == {
        "features": {"holds": "Holds a shelf", "fits": "Fits a 20 mm slot"},
        "physics": {"mass": ">0,<=0.05"},
        "ports": {"top": {"direction": [0, 0, -1]}},
        "interfaces": {"mount": {"left": None, "right": None}},
        # 'weight' is the mass, and is written as what it is.
        "match": {":old-bracket": {"mass": 5}},
        "has_private_dependencies": False,
    }
    # And it is what PartCAD reads, with nothing it cannot.
    from partcad import requirements

    declaration = requirements.parse(_requirements(package))
    assert not declaration.problems
    assert [port.name for port in declaration.ports] == ["top"]


def test_a_comparison_is_quoted_so_that_it_reads_back(session, package):
    _add(session, requirement="physics", name="mass", value="!0")
    assert "mass: '!0'" in (package / "partcad.yaml").read_text()


def test_the_rest_of_the_file_is_left_as_it_was_written(session, package):
    _add(session, requirement="physics", name="mass", value=">0")
    text = (package / "partcad.yaml").read_text()
    assert "# What was here before anything was required of it." in text
    assert text.index("bracket:") < text.index("old-bracket:")


def test_what_is_there_already_is_replaced_only_when_asked(session, package):
    _add(session, requirement="physics", name="mass", value=">0")
    with pytest.raises(JsonRpcError, match="required already.*--replace"):
        _add(session, requirement="physics", name="mass", value=">1")
    assert _requirements(package)["physics"] == {"mass": ">0"}
    _add(session, requirement="physics", name="mass", value=">1", replace=True)
    assert _requirements(package)["physics"] == {"mass": ">1"}


def test_text_from_a_form_is_read_as_yaml_reads_it(session, package):
    """What the IDE sends: each field as typed, '5' the number and '>5' the comparison."""
    _add(session, requirement="port", name="top", value={"position": ["0", "0", ">5"], "angle": "90"}, text=True)
    assert _requirements(package)["ports"] == {"top": {"position": [0, 0, ">5"], "angle": 90}}


def test_a_requirement_partcad_could_not_read_is_not_written(session, package):
    before = (package / "partcad.yaml").read_text()
    with pytest.raises(JsonRpcError, match="would not read"):
        _add(session, requirement="physics", name="mass", value=">heavy")
    assert (package / "partcad.yaml").read_text() == before


def test_an_interface_or_an_object_to_match_that_is_not_there_is_refused(session, package):
    before = (package / "partcad.yaml").read_text()
    with pytest.raises(JsonRpcError, match="interface 'nowhere' is not found"):
        _add(session, requirement="interface", name="nowhere")
    with pytest.raises(JsonRpcError, match="object to match, ':nothing', is not found"):
        _add(session, requirement="match", name=":nothing", value={"mass": 5})
    assert (package / "partcad.yaml").read_text() == before


def test_a_feature_something_names_is_removed_only_with_what_names_it(session, package):
    with pytest.raises(JsonRpcError, match="named by 'qual: sim: drop'.*--with-references"):
        _remove(session, requirement="feature", name="holds")
    assert _requirements(package) == {"features": {"holds": "Holds a shelf"}}

    _remove(session, requirement="feature", name="holds", with_references=True)
    bracket = _written(package)["bracket"]
    # Nothing is left of the section, and the simulation names no feature.
    assert "requirements" not in bracket
    assert bracket["qual"]["sim"]["drop"] == {"path": "sim:sim"}


def test_one_amount_or_one_instance_is_removed_alone(session, package):
    _add(session, requirement="match", name=":old-bracket", value={"mass": 5, "volume": 10})
    _add(session, requirement="interface", name="mount", instances=["left", "right"])
    _remove(session, requirement="match", name=":old-bracket", amounts=["weight"])
    _remove(session, requirement="interface", name="mount", instances=["left"])
    assert _requirements(package)["match"] == {":old-bracket": {"volume": 10}}
    assert _requirements(package)["interfaces"] == {"mount": {"right": None}}


def test_removing_what_is_not_required_says_so(session):
    with pytest.raises(JsonRpcError, match="'has_material' is not required"):
        _remove(session, requirement="has", name="material")


def test_an_alias_is_refused_since_its_requirements_are_its_sources(session, package):
    before = (package / "partcad.yaml").read_text()
    with pytest.raises(JsonRpcError, match="alias of '//reqdemo:bracket'.*change them there"):
        operations.requirements_add(
            session,
            {"package": "//reqdemo", "object": "copy", "requirement": "has", "name": "material", "value": True},
        )
    assert (package / "partcad.yaml").read_text() == before


def test_requirements_check_says_what_is_written_and_whether_it_can_be_changed(session):
    answer = operations.requirements_check(session, {"package": "//reqdemo", "object": "bracket"})
    assert answer["section"] == {"features": {"holds": "Holds a shelf"}}
    assert answer["declared"] == answer["section"]
    assert answer["editable"] is None
    assert "mass" in answer["physics_fields"]
    assert "private_dependencies" in answer["has_names"]

    alias = operations.requirements_check(session, {"package": "//reqdemo", "object": "copy"})
    assert alias["section"] is None
    assert alias["declared"] == {"features": {"holds": "Holds a shelf"}}
    assert "change them there" in alias["editable"]


def test_qual_add_replaces_an_entry_only_when_asked(session, package):
    params = {"package": "//reqdemo", "object": "bracket", "subtype": "topology", "name": "tolerance-surfaces"}
    operations.qual_add(session, {**params, "entry": {"minArea": 1.0}})
    session.partcad_ctx = pc.Context(str(package))
    with pytest.raises(JsonRpcError):
        operations.qual_add(session, {**params, "entry": {"minArea": 2.0}})
    assert _written(package)["bracket"]["qual"]["topology"] == {"tolerance-surfaces": {"minArea": 1.0}}
    operations.qual_add(session, {**params, "entry": {"minArea": 2.0}, "replace": True})
    assert _written(package)["bracket"]["qual"]["topology"] == {"tolerance-surfaces": {"minArea": 2.0}}


def test_a_requirement_shared_with_another_declaration_through_an_anchor_is_refused(tmp_path):
    """'ruamel' keeps an alias the object its anchor is: an edit of one would be an edit of both."""
    text = (
        "parts:\n"
        "  a:\n    type: basic\n    cuboid: 1\n    requirements: &shared\n      has_color: true\n"
        "  b:\n    type: basic\n    cuboid: 2\n    requirements: *shared\n"
        "  base: &base\n    type: basic\n    cuboid: 3\n    requirements:\n      has_finish: true\n"
        "  c:\n    <<: *base\n    cuboid: 4\n"
    )
    (tmp_path / "partcad.yaml").write_text(text)
    session = Session(EventEmitter(lambda event, payload: None))
    session.partcad = pc
    session.partcad_ctx = pc.Context(str(tmp_path))
    for name in ("b", "c"):
        with pytest.raises(JsonRpcError, match="YAML anchor or a merge key"):
            operations.requirements_add(
                session, {"object": name, "requirement": "has", "name": "weight", "value": True}
            )
    assert (tmp_path / "partcad.yaml").read_text() == text


def test_consecutive_edits_are_read_by_the_same_warm_context(session, package):
    """What the IDE does: one context, kept across a change and the check after it."""
    params = {"package": "//reqdemo", "object": "bracket"}
    operations.requirements_add(session, {**params, "requirement": "has", "name": "material", "value": True})
    assert operations.requirements_check(session, params)["section"]["has_material"] is True
    operations.requirements_remove(session, {**params, "requirement": "has", "name": "material"})
    assert "has_material" not in operations.requirements_check(session, params)["section"]


def test_the_package_of_the_object_is_reloaded_whatever_the_requirement_names():
    """'name' is a requirement here ('//lib:mount'), not the editor's object: both packages are checked."""
    import types

    ctx = types.SimpleNamespace(resolve_package_path=lambda package: package)
    targets, _ = operations._config_check_targets(ctx, {"package": "//here", "object": "bracket", "name": "//lib:m"})
    assert targets == ["//here", "//lib"]
    # The editor's own 'name', with no 'object', is still the object, and its package the one.
    targets, _ = operations._config_check_targets(ctx, {"package": "//here", "name": "//there:bracket"})
    assert targets == ["//there"]


def test_an_instance_has_the_requirements_of_the_object_it_is_of():
    assert operations._declared_name("bracket;length=10") == "bracket"
    assert operations._declared_name("room;medium=//pub/std:air") == "room"
    assert operations._declared_name("bracket") == "bracket"
