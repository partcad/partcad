#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for `simulate:`, the simulation plugins, and what validates a run.

A part says what it is; `simulate:` is where it says what it is supposed to do
once it is placed in a world and the world is run. Nothing here runs a
simulator: what is under test is everything around one -- how a declaration is
read, which scene and which plugin it resolves to, what the scene is asked for,
and what PartCAD makes of the two objects the plugin hands back.
"""

import asyncio
import os

import pytest

import partcad as pc
from partcad import output, simulation


def declaration(**config):
    return simulation.SimulationDeclaration("check", config)


#
# Reading a declaration
#


def test_a_named_declaration_per_simulation_is_the_usual_form():
    declared = simulation.declared(
        {
            "simulate": {
                "stands": {"validation": "True"},
                "falls": {"validation": "False"},
            }
        }
    )
    assert [entry.name for entry in declared] == ["stands", "falls"]
    assert declared[0].validation == "True"


def test_there_is_no_unnamed_short_form():
    """Telling one from the other would mean guessing from which keys are there.

    And the name is not ceremony: it is what '-f' selects, what the report
    prints beside the verdict, and what names the directory a run is written to.
    A section written that way is read as one simulation per key, which is what
    the configuration schema says it is.
    """
    declared = simulation.declared({"simulate": {"validation": "True"}})

    # Read as one simulation named 'validation' whose settings are the string
    # "True" - which is not a mapping, so it is reported and comes out empty
    # rather than half-understood. The configuration schema says the same thing
    # earlier, on the file.
    assert [entry.name for entry in declared] == ["validation"]
    assert declared[0].validation is None
    assert declared[0].simulation is None


def test_an_object_that_declares_nothing_has_no_simulations():
    assert simulation.declared({}) == []
    assert simulation.declared({"simulate": None}) == []


def test_a_declaration_that_names_no_scene_gets_the_built_in_one():
    """The common case: does this part stand up on its own."""
    entry = declaration(validation="True")
    assert entry.scene == "//builtin/scene:subject"


def test_there_is_no_default_plugin_because_partcad_implements_none():
    """A simulator is somebody's program, and PartCAD ships nobody's.

    So there is nothing to default to, and a declaration that names no plugin
    is reported rather than quietly run by one PartCAD picked.
    """
    assert declaration(validation="True").simulation is None
    assert not hasattr(simulation, "DEFAULT_SIMULATION")


def test_an_offset_is_the_identity_unless_one_is_stated():
    assert declaration().offset == [[0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0]
    assert declaration(offset=[[0, 0, 10], [0, 0, 1], 90]).offset == [[0.0, 0.0, 10.0], [0.0, 0.0, 1.0], 90.0]


def test_an_offset_that_is_not_a_location_is_reported_and_ignored():
    """A subject in the wrong place is correctable; refusing to run says less."""
    assert declaration(offset=[[0, 0], [0, 0, 1], 0]).offset == [[0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0]
    assert declaration(offset="up").offset == [[0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0]


#
# Validating a run
#


def result_with(before_z, after_z):
    return {
        "before": {"bodies": {"block": {"pos": [0.0, 0.0, before_z]}}},
        "after": {"bodies": {"block": {"pos": [0.0, 0.0, after_z]}}},
    }


def test_an_expression_over_before_and_after_decides_the_verdict():
    entry = declaration(validation='after["bodies"]["block"]["pos"][2] > 5.0')
    assert simulation.validate(entry, result_with(10.0, 9.9), "//p:block") is True
    assert simulation.validate(entry, result_with(10.0, 0.1), "//p:block") is False


def test_a_generator_expression_sees_both_objects():
    """The natural way to write one of these, and the one a locals scope breaks.

    A generator expression compiles to a function of its own, and a function
    body sees the enclosing globals but never a caller's locals - so with the
    two objects in a locals mapping this reads "name 'after' is not defined".
    """
    entry = declaration(
        validation="max(\n"
        '    abs(after["bodies"][name]["pos"][2] - before["bodies"][name]["pos"][2])\n'
        '    for name in before["bodies"]\n'
        ") < 1.0"
    )
    assert simulation.validate(entry, result_with(10.0, 10.5), "//p:block") is True
    assert simulation.validate(entry, result_with(10.0, 0.0), "//p:block") is False


def test_the_whole_result_is_available_beside_the_two():
    entry = declaration(validation='result["steps"] > 0')
    assert simulation.validate(entry, dict(result_with(1.0, 1.0), steps=5000), "//p:block") is True


def test_no_validation_is_no_verdict_rather_than_a_pass():
    """A run that states no condition ran; it did not pass anything."""
    assert simulation.validate(declaration(), result_with(1.0, 1.0), "//p:block") is None


def test_an_expression_that_will_not_compile_is_a_failed_validation():
    assert simulation.validate(declaration(validation="before ="), {}, "//p:block") is False


def test_an_expression_that_raises_is_a_failed_validation_not_a_failed_run():
    """The run happened; what did not work is the claim made about it."""
    assert simulation.validate(declaration(validation='after["bodies"]["nope"]'), result_with(1, 1), "//p:x") is False


def test_a_validation_expression_stays_a_validation_expression():
    """Not a security boundary - a package can declare a CadQuery part - but a
    reader of one should be able to see what it asserts without wondering what
    else it does."""
    assert simulation.validate(declaration(validation="__import__('os')"), {}, "//p:x") is False
    assert simulation.validate(declaration(validation="open('/etc/passwd')"), {}, "//p:x") is False
    # And the arithmetic it is actually for still works.
    assert simulation.validate(declaration(validation="abs(-2) == 2"), {}, "//p:x") is True


#
# Resolving what a declaration names
#


@pytest.fixture
def ctx(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "partcad.yaml").write_text("name: //sim\n", encoding="utf-8")
    return pc.Context(str(root))


@pytest.fixture
def plugin_ctx(tmp_path):
    """A context holding a package that implements a simulation, as a real one does."""
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "run_it.py").write_text("output = {'success': True}\n", encoding="utf-8")
    (root / "partcad.yaml").write_text(
        "name: //sim\n"
        "simulation:\n"
        "  toy:\n"
        "    path: run_it.py\n"
        "    pythonRequirements:\n      - somesim==1.2.3\n"
        "    format: mjcf\n"
        "    formatOptions:\n      static: false\n      flatten: true\n"
        "    duration: 10.0\n",
        encoding="utf-8",
    )
    return pc.Context(str(root))


def test_a_plugin_is_an_implementation_like_an_export_or_a_render_one(plugin_ctx):
    impl = simulation.resolve_plugin(plugin_ctx, "//", "//:toy")

    assert impl.section == output.SIMULATE
    assert impl.format_name == "toy"
    assert impl.script == "run_it.py"
    assert impl.config["format"] == "mjcf"
    # A physics run needs bodies that can move, which a scene does not mean.
    assert impl.config["formatOptions"] == {"static": False, "flatten": True}
    assert impl.python_requirements == ["somesim==1.2.3"]


def test_the_way_the_scene_reaches_the_plugin_is_not_handed_to_the_plugin(plugin_ctx):
    """'format' and 'formatOptions' configure the export, not the simulator."""
    impl = simulation.resolve_plugin(plugin_ctx, "//", "//:toy")
    assert "format" not in impl.parameters
    assert "formatOptions" not in impl.parameters
    assert impl.parameters["duration"] == 10.0


def test_a_plugin_the_named_package_does_not_declare_says_what_it_does(plugin_ctx):
    with pytest.raises(Exception, match="declares no simulation 'nosuch'"):
        simulation.resolve_plugin(plugin_ctx, "//", "//:nosuch")


def test_a_package_that_does_not_exist_is_reported(ctx):
    with pytest.raises(Exception, match="is not found"):
        simulation.resolve_plugin(ctx, "//", "//nowhere:mujoco")


#
# The scene the subject is placed in
#


@pytest.fixture
def package(tmp_path):
    """A package with one part that declares one simulation."""
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "cube.step").write_text("", encoding="utf-8")
    (root / "run_it.py").write_text("output = {'success': True}\n", encoding="utf-8")
    (root / "partcad.yaml").write_text(
        "name: //sim\n"
        # A package that simulates something names a plugin, and something has
        # to implement it: PartCAD implements none.
        "simulation:\n  toy:\n    path: run_it.py\n    format: mjcf\n"
        "parts:\n"
        "  block:\n"
        "    type: step\n"
        "    path: cube.step\n"
        "    simulate:\n"
        "      stands:\n"
        "        simulation: //sim:toy\n"
        "        offset: [[0, 0, 10], [0, 0, 1], 0]\n"
        '        validation: |\n          after["bodies"]["block"]["pos"][2] > 5.0\n',
        encoding="utf-8",
    )
    context = pc.Context(str(root))
    return context, context.get_project("//").get_part("block")


def test_the_subject_is_assigned_to_the_scene_unconditionally(ctx):
    params = simulation.scene_parameters(
        ctx,
        output.BUILTIN_SCENE_PACKAGE,
        "subject",
        declaration(offset=[[0, 0, 10], [0, 0, 1], 0]),
        "//p:block",
        "part",
    )

    assert params["subject"] == "//p:block"
    assert params["subject_kind"] == "part"
    # Seven whitespace-separated numbers rather than the bracketed form a
    # location is written in everywhere else; see 'format_offset'.
    assert params["subject_offset"] == "0 0 10 0 0 1 0"


def test_a_scene_that_cannot_hold_a_subject_is_not_a_simulation_scene(tmp_path):
    root = tmp_path / "other"
    root.mkdir()
    (root / "bench.assy").write_text("links:\n  []\n", encoding="utf-8")
    (root / "partcad.yaml").write_text("name: //other\nscenes:\n  bench:\n    type: assy\n", encoding="utf-8")
    other = pc.Context(str(root))

    with pytest.raises(Exception, match="declares no 'subject' parameter"):
        simulation.scene_parameters(other, "//", "bench", declaration(), "//p:block", "part")


def placed(assembly):
    """Every leaf of an assembly tree, as (name, translation) pairs."""
    found = []
    for child in assembly.children:
        item = child.item
        if getattr(item, "children", None):
            found.extend(placed(item))
        elif getattr(item, "kind", None) != "scene" and getattr(item, "kind", None) != "assembly":
            found.append((child.name, child.location.as_packed()[0]))
    return found


def test_a_parameter_value_can_always_be_spelled_in_an_instance_name(ctx):
    """Which is what decides how the offset is written, and is a rule of PartCAD's.

    An instance is asked for by name ("scene;a=1,b=2"), so ',', ';' and '=' are
    separators there and a value carrying one cannot be asked for at all -- which
    is why the configuration schema refuses a string default that does. A
    location written the usual way is nothing but those characters.
    """
    offset = simulation.format_offset([[0, 0, 10.5], [0, 0, 1], 90])

    assert offset == "0 0 10.5 0 0 1 90"
    assert not set(offset) & set(",;=")


def test_the_built_in_scene_places_the_subject_it_is_given(package):
    """The Jinja2 template is the whole of how one scene serves every object."""
    context, _part = package

    scene = context.get_scene(
        "%s:subject" % output.BUILTIN_SCENE_PACKAGE,
        {"subject": "//sim:block", "subject_kind": "part", "subject_offset": "0 0 10 0 0 1 0"},
    )
    asyncio.run(scene.do_instantiate())

    assert placed(scene) == [("subject", [0.0, 0.0, 10.0])]


def test_the_built_in_scene_with_no_subject_is_empty_rather_than_broken(ctx):
    """It is loaded by any context that simulates anything, asked or not."""
    scene = ctx.get_scene("%s:subject" % output.BUILTIN_SCENE_PACKAGE)
    assert scene is not None
    asyncio.run(scene.do_instantiate())
    assert placed(scene) == []


#
# One run, end to end, with the simulator stubbed out
#


def stub_run(monkeypatch, result):
    async def export(_ctx, _scene, _impl, directory):
        return os.path.join(directory, "scene.xml")

    async def run(_ctx, _impl, _directory, _scene_file, _declaration, _subject, _kind):
        return result

    monkeypatch.setattr(simulation, "_export_scene_async", export)
    monkeypatch.setattr(simulation, "_run_plugin_async", run)


def test_a_run_reports_the_verdict_and_what_the_plugin_said(package, monkeypatch):
    context, part = package
    stub_run(monkeypatch, dict(result_with(10.0, 9.9), simulator="stub"))
    (entry,) = simulation.of_shape(part)

    result = asyncio.run(simulation.run_async(context, part, "part", entry))

    assert result.passed is True
    assert result.failed is False
    assert result.result["simulator"] == "stub"
    assert result.to_dict()["object"] == "//sim:block"
    assert result.to_dict()["scene"] == simulation.DEFAULT_SCENE


def test_a_run_whose_validation_does_not_hold_is_a_failure(package, monkeypatch):
    context, part = package
    stub_run(monkeypatch, result_with(10.0, 0.0))
    (entry,) = simulation.of_shape(part)

    result = asyncio.run(simulation.run_async(context, part, "part", entry))

    assert result.passed is False
    assert result.failed is True


def test_a_run_that_could_not_happen_reports_why_rather_than_a_verdict(package, monkeypatch):
    context, part = package

    async def explode(*_args, **_kwargs):
        raise Exception("the sandbox would not start")

    monkeypatch.setattr(simulation, "_export_scene_async", explode)
    (entry,) = simulation.of_shape(part)

    result = asyncio.run(simulation.run_async(context, part, "part", entry))

    assert result.passed is None
    assert result.failed is True
    assert "would not start" in result.error


def test_a_part_reads_its_own_declaration(package):
    _context, part = package
    (entry,) = simulation.of_shape(part)
    assert entry.name == "stands"
    assert entry.offset == [[0.0, 0.0, 10.0], [0.0, 0.0, 1.0], 0.0]


def test_a_declaration_that_names_no_plugin_says_where_to_get_one(package, monkeypatch):
    """The one thing PartCAD cannot supply, and the message says who can."""
    context, part = package
    entry = simulation.SimulationDeclaration("stands", {"validation": "True"})

    result = asyncio.run(simulation.run_async(context, part, "part", entry))

    assert result.failed is True
    assert result.passed is None
    assert "names no 'simulation:'" in result.error
    assert simulation.KNOWN_SIMULATION in result.error
