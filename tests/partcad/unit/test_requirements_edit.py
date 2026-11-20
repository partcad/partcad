#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How one requirement is written into a 'requirements:' section, and taken out ('partcad.requirements_edit').

On the declaration as a mapping, as 'Project.edit_object_declaration' hands it
over; what reaches the file, and through the daemon, is pinned in
'tests/partcad_service_json_rpc/test_requirements_rpc.py'. What is pinned here is
that every edit leaves a section 'requirements.parse' reads as asked -- and that
one it would not read leaves the declaration as it was.
"""

import copy
import io

import pytest
import ruamel.yaml

from partcad import requirements
from partcad import requirements_edit as edit


def _declaration(section=None) -> dict:
    declaration = {"type": "basic", "cuboid": 10}
    if section is not None:
        declaration["requirements"] = section
    return declaration


def test_has_takes_every_spelling_and_names_what_it_takes():
    assert edit.has_key("material") == "has_material"
    assert edit.has_key("has-private-dependencies") == "has_private_dependencies"
    assert edit.has_key("mass") == "has_weight"
    with pytest.raises(edit.EditError, match="dependencies, private_dependencies"):
        edit.has_key("colour")
    assert edit.has_names() == [
        "color",
        "material",
        "finish",
        "weight",
        "dependencies",
        "private_dependencies",
    ]


@pytest.mark.parametrize(
    "legacy, features",
    [
        ("Holds a shelf.", {"general": "Holds a shelf."}),
        (["Holds a shelf.", "Fits a slot."], {"1": "Holds a shelf.", "2": "Fits a slot."}),
    ],
)
def test_a_section_written_before_it_had_structure_becomes_the_features_it_is_read_as(legacy, features):
    declaration = _declaration(legacy)
    before = requirements.parse(legacy).features
    edit.add(declaration, "has", "material", True)
    assert declaration["requirements"] == {"features": features, "has_material": True}
    assert requirements.parse(declaration["requirements"]).features == before


def test_a_heading_of_the_free_form_mapping_is_a_feature_by_that_name():
    declaration = _declaration({"general": "Holds a shelf."})
    with pytest.raises(edit.EditError, match="required already"):
        edit.add(declaration, "feature", "general", "Holds two shelves.")
    edit.add(declaration, "feature", "general", "Holds two shelves.", replace=True)
    assert declaration["requirements"] == {"features": {"general": "Holds two shelves."}}
    edit.remove(declaration, "feature", "general")
    assert "requirements" not in declaration


def test_a_port_is_written_with_what_was_said_and_nothing_else():
    declaration = _declaration()
    edit.add(declaration, "port", "top", {"position": None, "direction": [0, 0, -1], "angle": None})
    edit.add(declaration, "port", "side", None)
    assert declaration["requirements"]["ports"] == {"top": {"direction": [0, 0, -1]}, "side": None}
    with pytest.raises(edit.EditError, match="'facing' is not a key"):
        edit.add(declaration, "port", "back", {"facing": "down"})


def test_an_interface_any_instance_of_which_is_at_a_location_is_written_as_the_list():
    """A mapping under an interface names instances: a location for any of them has to be the list."""
    declaration = _declaration()
    edit.add(declaration, "interface", "m3", {"direction": [0, 0, 1]})
    assert declaration["requirements"]["interfaces"] == {"m3": [None, [0, 0, 1], None]}
    interface = requirements.parse(declaration["requirements"]).interfaces[0]
    assert interface.instances is None and interface.anywhere is not None


def test_an_instance_is_added_beside_those_required_already_in_whichever_shape():
    declaration = _declaration({"interfaces": {"m3": ["left"]}})
    edit.add(declaration, "interface", "m3", {"direction": [0, 0, 1]}, instances=["right"])
    assert declaration["requirements"]["interfaces"] == {"m3": {"left": None, "right": {"direction": [0, 0, 1]}}}
    with pytest.raises(edit.EditError, match="instance left of 'm3' is required already"):
        edit.add(declaration, "interface", "m3", None, instances=["left"])


def test_an_instance_cannot_be_added_to_a_location_any_instance_has_to_be_at():
    declaration = _declaration({"interfaces": {"m3": [None, [0, 0, 1], None]}})
    with pytest.raises(edit.EditError, match="any one of its instances"):
        edit.add(declaration, "interface", "m3", None, instances=["left"])


def test_the_last_instance_taken_out_takes_the_interface_out():
    declaration = _declaration({"interfaces": {"m3": "left"}})
    edit.remove(declaration, "interface", "m3", instances=["left"])
    assert "requirements" not in declaration


def test_a_physical_property_is_one_the_schema_knows():
    declaration = _declaration()
    edit.add(declaration, "physics", "inertia.ixx", ">0")
    edit.add(declaration, "physics", "centerOfMass", [None, None, "<5"])
    assert declaration["requirements"]["physics"] == {"inertia": {"ixx": ">0"}, "centerOfMass": [None, None, "<5"]}
    with pytest.raises(edit.EditError, match="'weight' is not a physical property"):
        edit.add(declaration, "physics", "weight", 1)
    with pytest.raises(edit.EditError, match="'mass' has no members"):
        edit.add(declaration, "physics", "mass.x", 1)
    with pytest.raises(edit.EditError, match="'iqq' is not a member of 'inertia'"):
        edit.add(declaration, "physics", "inertia.iqq", 1)


def test_a_match_is_held_to_amount_by_amount_and_weight_is_the_mass():
    declaration = _declaration({"match": {":old": {"weight": 5}}})
    with pytest.raises(edit.EditError, match="mass of ':old' is required already"):
        edit.add(declaration, "match", ":old", {"mass": 4})
    edit.add(declaration, "match", ":old", {"volume": "10%"})
    edit.add(declaration, "match", ":old", {"mass": 4}, replace=True)
    assert declaration["requirements"]["match"] == {":old": {"volume": "10%", "mass": 4}}
    with pytest.raises(edit.EditError, match="both the mass"):
        edit.add(declaration, "match", ":other", {"mass": 1, "weight": 2})
    edit.remove(declaration, "match", ":old", amounts=["weight"])
    assert declaration["requirements"]["match"] == {":old": {"volume": "10%"}}


def test_a_yes_or_no_requirement_replaces_its_other_spelling():
    declaration = _declaration({"has_mass": True})
    edit.add(declaration, "has", "weight", False, replace=True)
    assert declaration["requirements"] == {"has_weight": False}
    with pytest.raises(edit.EditError, match="true or false"):
        edit.add(declaration, "has", "material", "yes")


def test_a_feature_is_taken_out_of_what_names_it_only_when_asked():
    declaration = _declaration({"features": {"holds": "Holds a shelf", "fits": "Fits a slot"}})
    declaration["qual"] = {"sim": {"drop": {"path": "x:y", "feature": ["holds", "fits"]}}}
    declaration["fea"] = {"loaded": {"feature": "holds"}}
    with pytest.raises(edit.EditError, match="'qual: sim: drop', 'fea: loaded'"):
        edit.remove(declaration, "feature", "holds")
    said = edit.remove(declaration, "feature", "holds", with_references=True)
    assert "'qual: sim: drop', 'fea: loaded'" in said
    assert declaration["qual"]["sim"]["drop"] == {"path": "x:y", "feature": "fits"}
    assert declaration["fea"]["loaded"] == {}
    assert declaration["requirements"] == {"features": {"fits": "Fits a slot"}}


@pytest.mark.parametrize(
    "kind, name, value",
    [
        ("physics", "mass", ">heavy"),
        ("physics", "mass", ""),
        ("feature", "bad name!", "x"),
        ("port", "top", {"angle": [1, 2]}),
    ],
)
def test_a_requirement_partcad_would_not_read_leaves_the_declaration_as_it_was(kind, name, value):
    declaration = _declaration({"features": {"holds": "Holds a shelf"}})
    before = copy.deepcopy(declaration)
    with pytest.raises(edit.EditError):
        edit.add(declaration, kind, name, value)
    assert declaration == before


def test_a_problem_that_was_there_before_does_not_stop_another_edit():
    """Only what the edit makes unreadable refuses it: an old problem is the file's, not this edit's."""
    declaration = _declaration({"physics": {"mass": ">heavy"}})
    edit.add(declaration, "has", "material", True)
    assert declaration["requirements"]["has_material"] is True


def test_what_is_written_keeps_the_file_as_it_was_and_reads_back():
    yaml = ruamel.yaml.YAML()
    document = yaml.load("parts:\n  b:\n    type: basic  # kept\n    cuboid: 1\n")
    declaration = document["parts"]["b"]
    edit.add(declaration, "physics", "mass", "!0")
    edit.add(declaration, "interface", "m3", [[0, 0, 0], [0, 0, 1], None])
    written = io.StringIO()
    yaml.dump(document, written)
    text = written.getvalue()
    assert "# kept" in text
    assert "mass: '!0'" in text
    assert "m3: [[0, 0, 0], [0, 0, 1], null]" in text


def test_removing_what_is_not_there_says_so():
    with pytest.raises(edit.EditError, match="port 'top' is not required"):
        edit.remove(_declaration(), "port", "top")


def test_an_unknown_kind_is_refused():
    with pytest.raises(edit.EditError, match="feature, port, interface, physics, match, has"):
        edit.add(_declaration(), "colour", "x", 1)


def test_an_empty_value_says_that_yaml_reads_an_unquoted_comparison_so():
    spec = requirements.ValueSpec("")
    assert "quoted in YAML" in spec.error


# --- what an independent review of this module found -----------------------------


def test_every_entry_the_schema_refuses_is_its_own_and_an_old_one_does_not_hide_a_new_one():
    """The section's 'oneOf' reported one of them; an edit was then compared with whichever that was."""
    broken = {"interfaces": {"m3": {"a b": None}}, "ports": {"my port": None}}
    declaration = _declaration(copy.deepcopy(broken))
    # Taking one broken entry out is not refused for the other, which was already there.
    edit.remove(declaration, "interface", "m3")
    assert declaration["requirements"] == {"ports": {"my port": None}}
    # And adding a broken entry beside an old broken one is refused all the same.
    declaration = _declaration({"interfaces": {"m3": {"a b": None}}})
    with pytest.raises(edit.EditError, match="my port"):
        edit.add(declaration, "port", "my port", None)


def test_a_feature_written_both_ways_is_removed_both_ways():
    declaration = _declaration({"features": {"mount": "A"}, "mount": "B"})
    edit.remove(declaration, "feature", "mount")
    assert "requirements" not in declaration


def test_a_requirement_written_twice_loses_only_the_spelling_named():
    for named in ("has_mass", "mass", "has-mass"):
        declaration = _declaration({"has_weight": False, "has_mass": True})
        edit.remove(declaration, "has", named)
        assert declaration["requirements"] == {"has_weight": False}, named
    declaration = _declaration({"match": {":old": {"mass": 5, "weight": 6}}})
    problem = requirements.parse(declaration["requirements"]).problems[0]
    assert problem.address == {"requirement": "match", "name": ":old", "amount": "weight"}
    edit.remove(declaration, "match", ":old", amounts=[problem.address["amount"]])
    assert declaration["requirements"] == {"match": {":old": {"mass": 5}}}


def test_a_list_of_more_than_names_is_refused_rather_than_crashing():
    with pytest.raises(edit.EditError, match="not a list of names"):
        edit.remove(_declaration({"interfaces": ["m3", {"a": 1}]}), "interface", "m3")


def test_a_value_json_has_no_type_for_is_handed_over_as_its_text():
    import datetime
    import json

    data = edit.section_as_data({"deadline": datetime.date(2026, 3, 1)})
    assert json.dumps(data) == '{"deadline": "2026-03-01"}'


@pytest.mark.parametrize("name, desc", [("off", "yes"), ("1_000", "on"), ("no", "Holds a shelf")])
def test_what_is_written_reads_back_as_partcad_reads_the_file(name, desc):
    """'ruamel' writes YAML 1.2, PartCAD reads YAML 1.1: 'off:' unquoted would be the key False."""
    from partcad_utils import config_yaml

    yaml = ruamel.yaml.YAML()
    document = yaml.load("parts:\n  b:\n    type: basic\n    cuboid: 1\n")
    edit.add(document["parts"]["b"], "feature", name, desc)
    edit.add(document["parts"]["b"], "port", name, None)
    written = io.StringIO()
    yaml.dump(document, written)
    read = config_yaml.load(written.getvalue())["parts"]["b"]["requirements"]
    assert read == {"features": {name: desc}, "ports": {name: None}}
    assert requirements.parse(read).features == {name: desc}


@pytest.mark.parametrize("text", ["Fits a {{ M3 }} screw", "{% if x %}", "a {# note"])
def test_text_partcad_yaml_would_render_as_a_template_is_refused(text):
    declaration = _declaration()
    with pytest.raises(edit.EditError, match="Jinja2 template"):
        edit.add(declaration, "feature", "mount", text)
    assert "requirements" not in declaration


def test_what_is_written_is_checked_as_partcad_would_read_it_before_it_replaces_anything():
    """'read_back' compares what the edit changed with what 'config_yaml.load' makes of the text about to be written."""
    nothing = {"requirements": {}}
    written = {"requirements": {"features": {"off": "Holds"}}}
    check = edit.read_back("feature", "off")
    check(nothing, written, {"requirements": {"features": {"off": "Holds"}}})
    with pytest.raises(edit.EditError, match="read the feature 'off' back as nothing"):
        check(nothing, written, {"requirements": {"features": {False: "Holds"}}})
    # Only the entry the edit was about: what else was written by hand is read as its author meant.
    edit.read_back("physics", "mass")(
        {"requirements": {"has_material": "yes"}},
        {"requirements": {"physics": {"mass": ">0"}, "has_material": "yes"}},
        {"requirements": {"physics": {"mass": ">0"}, "has_material": True}},
    )
    # A removal reads back as nothing there.
    edit.read_back("port", "top")({"requirements": {"ports": {"top": None}}}, nothing, nothing)


def test_only_what_the_edit_changed_in_its_entry_has_to_read_back_as_written():
    """An amount of the same 'match:', or the other spelling of a 'has_', that the edit left alone is the author's."""
    edit.read_back("match", ":c")(
        {"requirements": {"match": {":c": {"volume": 123, "mass": 5}}}},
        {"requirements": {"match": {":c": {"volume": 123}}}},
        {"requirements": {"match": {":c": {"volume": 83}}}},
    )
    edit.read_back("has", "mass")(
        {"requirements": {"has_weight": "yes", "has_mass": True}},
        {"requirements": {"has_weight": "yes"}},
        {"requirements": {"has_weight": True}},
    )
    with pytest.raises(edit.EditError, match="back as"):
        edit.read_back("match", ":c")(
            {"requirements": {"match": {":c": {"volume": 123}}}},
            {"requirements": {"match": {":c": {"volume": 123, "mass": "1_000"}}}},
            {"requirements": {"match": {":c": {"volume": 83, "mass": 1000}}}},
        )
