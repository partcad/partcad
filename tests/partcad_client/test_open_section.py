#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the 'open:' section: applications a package declares.

The mechanism, not any one application. What each of the five PartCAD ships is
and how it is launched is 'test_external.py'; these are about the table being
*data* -- read out of a declaration, extensible by a package, and identical to
the hard-coded table it replaced.
"""

import os

import yaml

from partcad_client import external

BUILTIN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(external.__file__))),
    "partcad",
    "builtin",
    "open",
    "partcad.yaml",
)


def builtin_section():
    with open(BUILTIN, encoding="utf-8") as f:
        return yaml.safe_load(f)["open"]


def test_the_builtin_applications_are_read_from_the_declaration():
    """The table is the file, not a Python literal."""
    assert set(external.builtin_tools()) == set(builtin_section())


def test_a_package_adds_an_application_partcad_never_heard_of():
    """The whole point of the section."""
    tools = external.merge_tools(
        {"democad": {"displayName": "DemoCAD", "image": "example/democad:latest", "binaries": ["democad"]}}
    )

    assert tools["democad"].display_name == "DemoCAD"
    assert tools["democad"].binaries == ("democad",)
    # ...and it gets a container of its own, named the way every other one is.
    assert tools["democad"].container_name == "partcad-democad"
    # The built-ins are still there.
    assert "freecad" in tools


def test_a_package_replaces_a_builtin_of_the_same_name():
    """Which is how a plugin takes over the tool for its own engine."""
    tools = external.merge_tools({"mujoco": {"displayName": "MuJoCo (from the plugin)", "binaries": ["simulate"]}})

    assert tools["mujoco"].display_name == "MuJoCo (from the plugin)"


def test_an_unknown_field_does_not_break_a_declaration():
    """A package may know about a field this release does not."""
    tools = external.merge_tools({"democad": {"displayName": "DemoCAD", "somethingNewer": ["x"]}})

    assert tools["democad"].display_name == "DemoCAD"


def test_the_version_placeholder_pins_an_image_partcad_publishes():
    """So the release number is not written down twice."""
    assert external.TOOLS["kicad"].image.endswith(":" + external.__version__)
    assert "{version}" not in external.TOOLS["kicad"].image


def test_an_applications_own_file_is_opened_and_anything_else_imported():
    """What the 'fileArgs' templates and 'ownFormats' are between them.

    Blender is the case: 'blender <file>' opens a '.blend' and nothing else, so
    every other file reaches it through the expression the declaration carries.
    """
    blender = external.TOOLS["blender"]

    assert blender.file_arguments("/tmp/x.blend") == ("/tmp/x.blend",)
    args = blender.file_arguments("/tmp/x.stl")
    assert args[0] == "--python-expr"
    # The path is embedded as a Python literal, not pasted in raw.
    assert repr("/tmp/x.stl") in args[1]


def test_an_application_with_no_templates_just_takes_the_file():
    """Which is every application but Blender."""
    assert external.TOOLS["freecad"].file_arguments("/tmp/x.step") == ("/tmp/x.step",)


def test_a_front_end_gets_its_own_arguments():
    """Gazebo is three generations of one program, and they differ."""
    gazebo = external.TOOLS["gazebo"]

    assert gazebo.launch_args("gz") == ("sim",)
    assert gazebo.launch_args("ign") == ("gazebo",)
    assert gazebo.launch_args("gazebo") == ()


def test_nothing_declared_leaves_the_table_alone():
    """A daemon that could not be reached must not empty 'pc open'."""
    before = dict(external.TOOLS)
    external.use_tools(None)
    external.use_tools({})

    assert external.TOOLS == before
