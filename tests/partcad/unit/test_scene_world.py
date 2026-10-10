#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A scene's world: the gravity it states and the fluid it is filled with.

A scene states where things are. A simulation scene has to state two more
things, because the same arrangement comes out differently without them: which
way and how hard things fall, and what they fall through. Both are optional,
and both defaults are what every scene meant before a scene could say either --
the engine's own gravity, and vacuum -- so the tests below are as much about
what is *not* sent for a scene that states nothing as about what is sent for one
that does.

Nothing here runs a simulator or a sandbox. What reaches an exporter is the
request '_output_request()' builds, and that is what is looked at.
"""

import asyncio
import logging
import os
import types

import jsonschema
import pytest

import partcad as pc
from partcad import assembly_filter, output, physics, scene_world, simulation
from partcad.scene import Scene
from partcad.wrappers import mass_properties, wrapper_export
from partcad_utils import assy_lint

WATER = {"full": "Fresh water at 15 C", "density": 999.1, "viscosity": 0.001138}


def package(tmp_path, scenes, materials=None, extra="", name="//sim"):
    """A package holding 'scenes', each an empty 'assy' scene with whatever else it declares."""
    root = tmp_path / "workspace"
    root.mkdir(exist_ok=True)
    (root / "empty.assy").write_text("links:\n  []\n", encoding="utf-8")
    lines = ["name: %s" % name]
    if materials:
        lines.append("materials:")
        for material_name, facts in materials.items():
            lines.append("  %s:" % material_name)
            for key, value in facts.items():
                lines.append("    %s: %r" % (key, value) if not isinstance(value, str) else "    %s: %s" % (key, value))
    lines.append("scenes:")
    for scene_name, declared in scenes.items():
        lines.append("  %s:" % scene_name)
        lines.append("    type: assy")
        lines.append("    path: empty.assy")
        for key, value in declared.items():
            lines.append("    %s: %s" % (key, value))
    (root / "partcad.yaml").write_text("\n".join(lines) + "\n" + extra, encoding="utf-8")
    return pc.Context(str(root))


def request_for(ctx, shape, **parameters):
    """What an implementation declaring 'parameters' would be handed for 'shape'."""
    impl = types.SimpleNamespace(parameters=parameters)
    return asyncio.run(shape._output_request(ctx, {"name": "envelope"}, impl, {}))


#
# The schema
#


def schema_errors(config):
    schema = assy_lint.get_schema(assy_lint.PARTCAD_SCHEMA)
    return [error.message for error in jsonschema.Draft7Validator(schema).iter_errors(config)]


def test_the_schema_takes_a_gravity_and_a_medium_on_a_scene():
    assert not schema_errors(
        {
            "scenes": {
                "tank": {
                    "type": "assy",
                    "gravity": [0, 0, -9.81],
                    "medium": "//pub/std/manufacturing/material/fluid:water",
                },
                "world": {"type": "sim-gazebo:world", "gravity": [0, 0, -1.62], "medium": ":brine"},
            }
        }
    )


@pytest.mark.parametrize(
    "gravity",
    [[0, 0], [0, 0, -9.81, 0], "0 0 -9.81", -9.81, [0, 0, "-9.81 m/s^2"]],
    ids=["two", "four", "a-string", "a-scalar", "a-unit-string"],
)
def test_the_schema_takes_gravity_as_three_numbers_and_nothing_else(gravity):
    """In m/s^2 and with no unit spelled: see 'scene_world' for why."""
    assert schema_errors({"scenes": {"tank": {"type": "assy", "gravity": gravity}}})


def test_the_schema_takes_a_viscosity_on_a_material_and_refuses_a_non_positive_one():
    assert not schema_errors({"materials": {"water": dict(WATER)}})
    assert schema_errors({"materials": {"water": dict(WATER, viscosity=0)}})


#
# The material
#


def test_viscosity_is_dynamic_and_in_pascal_seconds(tmp_path):
    ctx = package(tmp_path, {}, materials={"water": WATER})
    water = ctx.get_project("//").get_material("water")

    assert water.viscosity == pytest.approx(0.001138)
    # SI, like every physical quantity PartCAD states: the datasheet's number.
    assert water.info()["Viscosity"] == "0.001138 Pa*s"


def test_a_material_that_states_no_viscosity_reports_none(tmp_path):
    ctx = package(tmp_path, {}, materials={"pla": {"density": 1320.0}})
    pla = ctx.get_project("//").get_material("pla")

    assert pla.viscosity is None
    assert "Viscosity" not in pla.info()


#
# What a scene states, and what it does not
#


def test_a_scene_that_states_nothing_is_the_engines_gravity_in_a_vacuum(tmp_path):
    ctx = package(tmp_path, {"bench": {}})
    bench = ctx.get_scene("//sim:bench")

    assert bench.gravity is None
    assert bench.medium_reference() is None
    assert bench.get_medium(ctx) is None
    assert bench.world_facts(ctx) is None


def test_the_built_in_scene_states_neither():
    """Earth as the engine has it, in a vacuum: what every simulation meant until now."""
    ctx = pc.Context(".")
    subject = ctx.get_scene("%s:subject" % output.BUILTIN_SCENE_PACKAGE)
    assert subject.world_facts(ctx) is None


def test_gravity_is_a_vector_in_metres_per_second_squared(tmp_path):
    ctx = package(tmp_path, {"moon": {"gravity": "[0, 0, -1.62]"}})
    assert ctx.get_scene("//sim:moon").gravity == [0.0, 0.0, -1.62]


@pytest.mark.parametrize("declared", ["[0, 0]", "'0 0 -9.81'", "[0, 0, true]", "[0, 0, .nan]"])
def test_a_gravity_that_is_not_three_finite_numbers_is_refused(tmp_path, declared):
    """Raised rather than defaulted: the default is a different world."""
    ctx = package(tmp_path, {"bad": {"gravity": declared}})
    with pytest.raises(scene_world.WorldError, match="gravity"):
        ctx.get_scene("//sim:bad").gravity


def test_a_gravity_a_thousand_times_too_large_is_reported(tmp_path, caplog):
    """The mistake m/s^2 invites -- a vector in mm/s^2 -- is the one easy to catch."""
    ctx = package(tmp_path, {"mm": {"gravity": "[0, 0, -9806.65]"}})
    with caplog.at_level(logging.WARNING):
        facts = ctx.get_scene("//sim:mm").world_facts(ctx)
    assert facts == {"gravity": [0.0, 0.0, -9806.65]}
    assert "m/s^2" in caplog.text


#
# The medium, resolved the way a part's material is
#


def test_a_medium_is_a_material_resolved_against_the_scenes_own_package(tmp_path):
    ctx = package(tmp_path, {"tank": {"medium": "':water'"}}, materials={"water": WATER})
    tank = ctx.get_scene("//sim:tank")

    assert tank.medium_reference() == ":water"
    assert tank.get_medium(ctx).name == "water"
    assert tank.world_facts(ctx) == {
        "medium": {"material": "//sim:water", "density": 999.1, "viscosity": 0.001138},
    }


def test_a_medium_may_be_catalogued_in_another_package(tmp_path):
    ctx = package(
        tmp_path,
        {"tank": {"medium": "//sim/fluids:seawater", "gravity": "[0, 0, -9.81]"}},
        extra="dependencies:\n  fluids:\n    type: local\n    path: fluids\n",
    )
    fluids = tmp_path / "workspace" / "fluids"
    fluids.mkdir()
    (fluids / "partcad.yaml").write_text(
        "materials:\n  seawater:\n    density: 1026.0\n    viscosity: 0.00122\n", encoding="utf-8"
    )

    assert ctx.get_scene("//sim:tank").world_facts(ctx) == {
        "gravity": [0.0, 0.0, -9.81],
        "medium": {"material": "//sim/fluids:seawater", "density": 1026.0, "viscosity": 0.00122},
    }


def test_a_medium_nothing_answers_to_is_refused_naming_the_scene(tmp_path):
    """A vacuum where the scene said water would be a confident wrong answer."""
    ctx = package(tmp_path, {"tank": {"medium": "':nosuch'"}})
    with pytest.raises(scene_world.WorldError, match=r"//sim:tank.*//sim:nosuch"):
        ctx.get_scene("//sim:tank").world_facts(ctx)


def test_a_medium_that_states_neither_fact_is_carried_and_reported(tmp_path, caplog):
    ctx = package(tmp_path, {"tank": {"medium": "':mystery'"}}, materials={"mystery": {"full": "Something"}})
    with caplog.at_level(logging.WARNING):
        facts = ctx.get_scene("//sim:tank").world_facts(ctx)
    assert facts == {"medium": {"material": "//sim:mystery"}}
    assert "nothing to drag or buoy" in caplog.text


def test_info_reports_the_world_as_the_facts_a_simulation_uses(tmp_path):
    ctx = package(tmp_path, {"tank": {"medium": "':water'", "gravity": "[0, 0, -9.81]"}}, materials={"water": WATER})

    info = ctx.get_scene("//sim:tank").shape_info(ctx)

    assert info["Gravity"] == "0, 0, -9.81 m/s^2"
    assert info["Medium"]["Name"] == "water"
    assert "Viscosity" in info["Medium"]


def test_info_of_a_broken_world_says_what_is_wrong_rather_than_failing(tmp_path):
    ctx = package(tmp_path, {"tank": {"medium": "':nosuch'"}})
    info = ctx.get_scene("//sim:tank").shape_info(ctx)
    assert any("no material answers" in error for error in info["Errors"])


#
# What reaches an exporter
#


def test_a_physics_exporter_is_handed_the_world(tmp_path):
    ctx = package(tmp_path, {"tank": {"medium": "':water'", "gravity": "[0, 0, -1.62]"}}, materials={"water": WATER})

    request = request_for(ctx, ctx.get_scene("//sim:tank"), properties=True)

    assert request[output.WORLD_KEY] == {
        "gravity": [0.0, 0.0, -1.62],
        "medium": {"material": "//sim:water", "density": 999.1, "viscosity": 0.001138},
    }
    # The key the sandbox side reads it by is the same one.
    assert output.WORLD_KEY == wrapper_export.WORLD_KEY


def test_a_scene_that_states_nothing_sends_nothing(tmp_path):
    """So an exporter that has never heard of a world writes what it always wrote."""
    ctx = package(tmp_path, {"bench": {}})
    request = request_for(ctx, ctx.get_scene("//sim:bench"), properties=True)
    assert output.WORLD_KEY not in request


def test_a_file_type_with_no_physics_is_not_handed_a_world(tmp_path):
    """A drawing has nowhere to write a gravity, and must not load a package to find one."""
    ctx = package(tmp_path, {"tank": {"medium": "':nosuch'"}})
    # Not even resolved: the medium here answers to nothing, and a PNG of the
    # tank is still a PNG of the tank.
    request = request_for(ctx, ctx.get_scene("//sim:tank"))
    assert output.WORLD_KEY not in request


def test_an_assembly_has_no_world_to_send(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "empty.assy").write_text("links:\n  []\n", encoding="utf-8")
    (root / "partcad.yaml").write_text("assemblies:\n  arm:\n    type: assy\n    path: empty.assy\n", encoding="utf-8")
    ctx = pc.Context(str(root))

    request = request_for(ctx, ctx.get_assembly("//:arm"), properties=True)

    assert output.WORLD_KEY not in request


def test_a_filtered_view_of_a_scene_is_the_same_world(tmp_path):
    """A '--filter' picks which links a file is of, not which world they are in."""
    ctx = package(tmp_path, {"tank": {"gravity": "[0, 0, -1.62]"}})
    tank = ctx.get_scene("//sim:tank")
    view = assembly_filter.derive(tank, [])

    assert isinstance(view, Scene)
    assert view.world_facts(ctx) == {"gravity": [0.0, 0.0, -1.62]}


#
# What a body displaces: the one fact buoyancy needs that a mass cannot give
#

# What a 20 mm cube measures as it is built (see 'shape_measure').
CUBE = {
    "volume": 8000.0,
    "centroid": [0.0, 0.0, 0.0],
    "unitInertia": [[1.0e8 * 8 / 6, 0.0, 0.0], [0.0, 1.0e8 * 8 / 6, 0.0], [0.0, 0.0, 1.0e8 * 8 / 6]],
    "solids": 1,
}


def test_every_shape_is_handed_over_with_the_volume_its_solid_encloses():
    """Measured, never derived: a float that states its mass still displaces its whole solid."""
    stated, _sources = physics.resolve({"mass": 0.003}, measurements=CUBE)
    derived, sources = physics.resolve(None, measurements=CUBE, fallback=(2700.0, "x"))

    assert stated["volume"] == derived["volume"] == 8000.0
    assert sources["volume"] == "measured"
    # Not the volume a mass and a density would imply, which for the float
    # would be that of 3 g of aluminium.
    assert stated["mass"] == 0.003


def test_a_shape_that_encloses_nothing_is_handed_no_volume():
    resolved, _sources = physics.resolve({"mass": 1.0}, measurements={"volume": None, "solids": 0})
    assert "volume" not in resolved


def test_a_body_displaces_the_sum_of_what_its_parts_enclose():
    parts = [({"mass": 1.0, "volume": 8000.0}, None), ({"mass": 2.0, "volume": 1000.0}, [[10, 0, 0], [0, 0, 1], 90])]

    assert mass_properties.volume_of(parts) == 9000.0
    # And the placements change nothing about it, or about the mass beside it.
    assert mass_properties.of_body(parts)["mass"] == 3.0
    assert "volume" not in mass_properties.combined([physics_ for physics_, _ in parts])


def test_a_body_with_a_part_of_unknown_volume_has_no_volume_rather_than_part_of_one():
    """A body buoyed by part of what it displaces would float wrongly, and nothing could tell."""
    assert mass_properties.volume_of([({"volume": 8000.0}, None), ({"mass": 1.0}, None)]) is None
    assert mass_properties.volume_of([({"volume": 0.0}, None)]) is None
    assert mass_properties.volume_of([]) is None


def test_no_exporter_reports_the_volume_as_a_property_it_cannot_state():
    """It is a measurement handed over for buoyancy, not a property of the part."""
    import importlib.util

    path = os.path.join(os.path.dirname(pc.__file__), "builtin", "export", "export_urdf.py")
    spec = importlib.util.spec_from_file_location("export_urdf_under_test", path)
    export_urdf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(export_urdf)

    assert "volume" in export_urdf.URDF_STATED


def test_the_properties_index_does_not_mistake_the_world_for_a_shape():
    request = {
        "wrapped": {"name": "pkg:leaf", "brep": "x", "properties": {"color": "#FFFFFF"}},
        wrapper_export.WORLD_KEY: {"gravity": [0.0, 0.0, -9.81], "medium": {"material": "pkg:water"}},
    }
    assert wrapper_export.properties_index(request) == {"pkg:leaf": {"color": "#FFFFFF"}}


def test_a_broken_world_fails_the_file_and_says_why(tmp_path, monkeypatch):
    """Reported against the scene, with nothing written, as a bad filter is."""
    ctx = package(tmp_path, {"tank": {"medium": "':nosuch'"}})
    tank = ctx.get_scene("//sim:tank")
    impl = types.SimpleNamespace(
        parameters={"properties": True}, format_name="toy", link_filter=None, section=output.EXPORT
    )
    monkeypatch.setattr(tank, "output_getopts", lambda *args, **kwargs: (impl, str(tmp_path / "tank.toy")))

    async def no_script(_ctx, _impl):
        return "write_it.py"

    async def must_not_run(*args, **kwargs):
        raise AssertionError("an implementation was run for a scene whose world is broken")

    monkeypatch.setattr(tank, "_materialize_output_script", no_script)
    monkeypatch.setattr(tank, "_run_implementation_async", must_not_run)

    asyncio.run(tank._render_one_async(ctx, {"name": "envelope"}, "toy", None, None, None, None, {}))

    assert any("no material answers" in error for error in tank.errors)


#
# A simulation of a scene with a world
#

TOY_PLUGIN = (
    "simulation:\n  toy:\n    path: run_it.py\n    format: toyfmt\n"
    "export:\n  toyfmt:\n    path: write_it.py\n    extension: tf\n    properties: true\n"
)


def simulating(tmp_path, scene_declares):
    """A package whose part is simulated in a scene of its own, declaring 'scene_declares'."""
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "cube.step").write_text("", encoding="utf-8")
    (root / "run_it.py").write_text("output = {'success': True}\n", encoding="utf-8")
    (root / "write_it.py").write_text("output = {'success': True}\n", encoding="utf-8")
    (root / "tank.assy").write_text("links:\n  []\n", encoding="utf-8")
    world = "".join("    %s: %s\n" % item for item in scene_declares.items())
    (root / "partcad.yaml").write_text(
        "name: //sim\n"
        + TOY_PLUGIN
        + "materials:\n  water:\n    density: 999.1\n    viscosity: 0.001138\n"
        + "scenes:\n  tank:\n    type: assy\n    path: tank.assy\n"
        + "    parameters:\n      subject:\n        type: string\n        default: ''\n"
        + world
        + "parts:\n  block:\n    type: step\n    path: cube.step\n"
        + "    simulate:\n      sinks:\n        simulation: //sim:toy\n        scene: :tank\n"
        + "        validation: 'True'\n",
        encoding="utf-8",
    )
    context = pc.Context(str(root))
    return context, context.get_project("//").get_part("block")


def stub_run(monkeypatch):
    async def export(_ctx, _scene, _impl, directory):
        return os.path.join(directory, "scene.tf")

    async def run(_ctx, _impl, _directory, _scene_file, _declaration, _subject, _kind):
        return {"success": True, "before": {}, "after": {}}

    monkeypatch.setattr(simulation, "_export_scene_async", export)
    monkeypatch.setattr(simulation, "_run_plugin_async", run)


def asked(monkeypatch):
    """Every question a simulation's answer is cached under, as it is asked."""
    questions = []
    original = simulation.cache_artifacts.question_hash

    def question_hash(name, key, question, files):
        questions.append(question)
        return original(name, key, question, files)

    monkeypatch.setattr(simulation.cache_artifacts, "question_hash", question_hash)
    return questions


def test_a_run_is_cached_under_the_facts_its_world_resolved_to(tmp_path, monkeypatch):
    """The density behind ':water' lives in a package that can change without this one."""
    context, part = simulating(tmp_path, {"medium": "':water'", "gravity": "[0, 0, -9.81]"})
    stub_run(monkeypatch)
    questions = asked(monkeypatch)
    (entry,) = simulation.of_shape(part)

    result = asyncio.run(simulation.run_async(context, part, "part", entry))

    assert result.error is None
    (question,) = questions
    assert question["world"] == {
        "gravity": [0.0, 0.0, -9.81],
        "medium": {"material": "//sim:water", "density": 999.1, "viscosity": 0.001138},
    }


def test_a_scene_that_states_no_world_keeps_the_key_it_had(tmp_path, monkeypatch):
    context, part = simulating(tmp_path, {})
    stub_run(monkeypatch)
    questions = asked(monkeypatch)
    (entry,) = simulation.of_shape(part)

    asyncio.run(simulation.run_async(context, part, "part", entry))

    (question,) = questions
    assert "world" not in question


def test_a_run_in_a_medium_nothing_answers_to_fails_saying_so(tmp_path, monkeypatch):
    context, part = simulating(tmp_path, {"medium": "':nosuch'"})
    stub_run(monkeypatch)
    (entry,) = simulation.of_shape(part)

    result = asyncio.run(simulation.run_async(context, part, "part", entry))

    assert result.failed is True
    assert result.passed is None
    assert "no material answers" in result.error
