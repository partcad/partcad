#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A folder holding a '.pcignore' is not part of the package around it.

Laid out the way a plugin package keeps its tests: the plugin at the top, its
'tests/' folder marked, and a consumer package inside that imports the plugin
as a user's would. The plugin must not see the consumer as a subpackage, and
the consumer must be a workspace of its own rather than climbing to the plugin.
"""

import importlib.util
import os

import pytest

import partcad as pc
from partcad import source_key
from partcad_utils import lint_context, pcignore, workspace


@pytest.fixture
def tree(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "sub").mkdir(parents=True)
    (plugin / "tests" / "consumer").mkdir(parents=True)
    (plugin / "partcad.yaml").write_text("desc: The plugin\n")
    (plugin / "script.py").write_text("print('plugin')\n")
    (plugin / "sub" / "partcad.yaml").write_text("desc: A real subpackage\n")
    (plugin / "tests" / pcignore.IGNORE_FILE).write_text("")
    (plugin / "tests" / "test_helper.py").write_text("print('test')\n")
    (plugin / "tests" / "consumer" / "partcad.yaml").write_text(
        "desc: Uses the plugin\ndependencies:\n  plugin:\n    type: local\n    path: ../..\n"
    )
    return plugin


def test_an_ignored_folder_is_not_a_subpackage(tree):
    ctx = pc.Context(str(tree))
    names = [p["name"] if isinstance(p, dict) else p for p in ctx.get_all_packages(has_stuff=False)]
    assert "//sub" in names
    assert not any(name.startswith("//tests") for name in names)
    assert ctx.get_project("//tests/consumer") is None
    assert ctx.get_project("//").get_child_project_names(absolute=False) == ["sub"]


def test_a_package_inside_one_is_a_workspace_of_its_own(tree):
    consumer = tree / "tests" / "consumer"
    ctx = pc.Context(str(consumer))
    assert ctx.root_path == str(consumer)
    # ...that still reaches the plugin it imports.
    assert ctx.get_project("//plugin") is not None
    # The client finds the same root, so it talks to the same daemon.
    assert workspace.determine_root_path(str(consumer)) == str(consumer)


def test_without_the_marker_the_climb_goes_on(tree):
    os.remove(tree / "tests" / pcignore.IGNORE_FILE)
    (tree / "tests" / "partcad.yaml").write_text("desc: Now a subpackage\n")
    assert workspace.determine_root_path(str(tree / "tests" / "consumer")) == str(tree)
    assert pc.Context(str(tree / "tests" / "consumer")).root_path == str(tree)


def test_an_ignored_folder_is_not_the_package_s_source(tree):
    sources = [relative for relative, _path in source_key._sources(str(tree))]
    assert sources == ["script.py"]


def test_the_packages_above_a_file_stop_at_an_ignored_folder(tree):
    above = [directory for directory, _config in lint_context._packages_above(str(tree / "tests" / "consumer"))]
    assert above == [str(tree / "tests" / "consumer")]


def test_the_marker_is_a_file(tmp_path):
    (tmp_path / pcignore.IGNORE_FILE).mkdir()
    assert not pcignore.is_ignored(str(tmp_path))
    assert importlib.util.find_spec("partcad_utils.pcignore") is not None
