#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an object declares under 'qual:', and the older keys it still reads (see 'partcad.qual.config')."""

import pytest

from partcad.qual import config as qual_config
from partcad.qual import registry


def test_a_built_in_checks_parameters_are_read_under_its_subtype():
    config = {"qual": {"topology": {"interference": {"minVolume": 0.01}}}}
    assert qual_config.params(config, "topology", "interference") == {"minVolume": 0.01}
    assert qual_config.params(config, "basic", "interference") == {}


def test_qual_wins_over_the_older_key_and_the_older_key_is_still_read():
    config = {
        "interference": {"minVolume": 1.0, "minFraction": 0.5},
        "qual": {"topology": {"interference": {"minVolume": 0.01}}},
    }
    assert qual_config.params(config, "topology", "interference", legacy="interference") == {
        "minVolume": 0.01,
        "minFraction": 0.5,
    }
    assert qual_config.params(
        {"connectivity": {"requireAnchored": False}}, "basic", "connectivity", legacy="connectivity"
    ) == {"requireAnchored": False}


def test_an_entry_that_names_a_plugin_is_a_declaration_not_parameters():
    config = {
        "qual": {
            "other": {"budgets": {"path": "//pub/qual/lockwire:lockwire", "desc": "Budgets", "lockfile": "rover.yaml"}},
            "topology": {"tolerance-surfaces": {"minArea": 1.0}},
        }
    }
    (declaration,) = qual_config.declared(config, "other")
    assert (declaration.subtype, declaration.name, declaration.path, declaration.desc) == (
        "other",
        "budgets",
        "//pub/qual/lockwire:lockwire",
        "Budgets",
    )
    # Everything but what is about the entry is the plugin's.
    assert declaration.params == {"lockfile": "rover.yaml"}
    # A built-in check's parameters are not a declaration.
    assert qual_config.declared(config, "topology", builtin_names=["tolerance-surfaces"]) == []


def test_a_plugin_cannot_take_a_built_in_checks_name(caplog):
    # Said once per command; another test in this process may have said it already.
    qual_config._reported.clear()
    config = {"qual": {"topology": {"interference": {"path": "x:y"}}}}
    assert qual_config.declared(config, "topology", builtin_names=["interference"]) == []
    assert "is a built-in check" in caplog.text


def test_an_entry_that_is_neither_is_reported(caplog):
    # Said once per command; another test in this process may have said it already.
    qual_config._reported.clear()
    assert qual_config.declared({"qual": {"basic": {"nothing": {"a": 1}}}}, "basic", builtin_names=["cad"]) == []
    assert "names no built-in check and no plugin" in caplog.text


def test_an_unknown_subtype_is_reported(caplog):
    # Said once per command; another test in this process may have said it already.
    qual_config._reported.clear()
    qual_config.section({"qual": {"validation": {}}})
    assert "is not a subtype of qualification" in caplog.text


def test_simulations_are_read_from_qual_sim_and_from_the_older_section():
    config = {
        "qual": {"sim": {"stands": {"path": "sim-mujoco:mujoco", "validation": "True"}}},
        "simulate": {
            "floats": {"simulation": "sim-mujoco:mujoco", "validation": "True"},
            "stands": {"simulation": "other:other"},
        },
    }
    simulations = dict(qual_config.simulations(config))
    assert list(simulations) == ["stands", "floats"]
    # 'qual: sim:' wins a name declared twice, and the older 'simulation:' is
    # read as the 'path:' it now is.
    assert simulations["stands"]["path"] == "sim-mujoco:mujoco"
    assert simulations["floats"]["path"] == "sim-mujoco:mujoco"
    assert "simulation" not in simulations["floats"]


def test_a_simulation_declaration_reads_path_and_the_older_simulation():
    from partcad import simulation

    assert simulation.SimulationDeclaration("a", {"path": "p:q"}).simulation == "p:q"
    assert simulation.SimulationDeclaration("a", {"simulation": "p:q"}).simulation == "p:q"
    (declared,) = simulation.declared({"qual": {"sim": {"a": {"path": "p:q", "validation": "True"}}}})
    assert (declared.name, declared.simulation, declared.validation) == ("a", "p:q", "True")


@pytest.mark.parametrize(
    "selection, chosen",
    [
        (None, ("basic", "topology", "sim", "other")),
        ([], ("basic", "topology", "sim", "other")),
        ("other", ("other",)),
        (["other", "basic"], ("basic", "other")),
        (["simulation"], ("sim",)),
    ],
)
def test_a_selection_of_subtypes_is_read_in_presentation_order(selection, chosen):
    assert qual_config.subtypes_of(selection) == chosen


def test_an_unknown_subtype_is_refused():
    with pytest.raises(ValueError, match="is not a subtype"):
        qual_config.subtypes_of(["validation"])


def test_every_built_in_check_is_of_a_subtype_and_those_that_point_at_geometry_are_topology():
    subtypes = {qual.name: qual.SUBTYPE for qual in registry.builtin()}
    assert set(subtypes.values()) <= set(qual_config.SUBTYPES)
    assert {name for name, subtype in subtypes.items() if subtype == "topology"} == {
        "interference",
        "tolerance-surfaces",
        "tolerance-edges",
    }
    assert subtypes["sim"] == "sim"
    assert subtypes["cad"] == subtypes["manufacturability"] == "basic"


def test_a_run_of_one_subtype_selects_its_checks():
    quals = registry.builtin()
    assert [qual.name for qual in registry.select(quals, ["topology"])] == [
        "interference",
        "tolerance-surfaces",
        "tolerance-edges",
    ]
    assert [qual.name for qual in registry.select(quals, None, "tolerance")] == [
        "tolerance-surfaces",
        "tolerance-edges",
    ]
    assert registry.select(quals, ["other"]) == []


def test_the_old_names_are_the_new_modules():
    from partcad.qual import catalog, qualification, report
    from partcad.test import all as old_all
    from partcad.test import catalog as old_catalog
    from partcad.test import report as old_report
    from partcad.test import test as old_test

    assert old_test.Test is qualification.Qualification
    assert old_report is report and old_catalog is catalog
    assert old_all.tests is registry.builtin


def test_an_entry_is_written_into_the_objects_qual_section(tmp_path):
    import yaml

    import partcad as pc

    (tmp_path / "partcad.yaml").write_text(
        "# kept as written\nparts:\n  bracket:\n    type: brep\n    path: bracket.brep\n"
    )
    project = pc.Context(str(tmp_path)).get_project("//")

    assert project.add_qual_config("part", "bracket", "topology", "tolerance-surfaces", {"minArea": 1.0})
    assert project.add_qual_config("part", "bracket", "other", "budgets", {"path": "lockwire:lockwire"})
    # Nowhere to write it: the file declares no such object.
    assert not project.add_qual_config("part", "absent", "other", "budgets", {"path": "lockwire:lockwire"})
    assert not project.add_qual_config("part", "bracket", "validation", "x", {})

    text = (tmp_path / "partcad.yaml").read_text()
    assert text.startswith("# kept as written")
    assert yaml.safe_load(text)["parts"]["bracket"]["qual"] == {
        "topology": {"tolerance-surfaces": {"minArea": 1.0}},
        "other": {"budgets": {"path": "lockwire:lockwire"}},
    }


@pytest.mark.parametrize(
    "declaration, held",
    [
        ({}, True),
        ({"connectivity": {"requireAnchored": False}}, False),
        ({"qual": {"basic": {"connectivity": {"requireAnchored": False}}}}, False),
        # 'qual:' wins over the older key, as it does for the check itself.
        (
            {
                "connectivity": {"requireAnchored": False},
                "qual": {"basic": {"connectivity": {"requireAnchored": True}}},
            },
            True,
        ),
    ],
)
def test_the_editor_reads_connectivity_where_the_check_does(declaration, held):
    from partcad_utils.lint_context import _held_to_connectivity

    assert _held_to_connectivity(declaration) is held
