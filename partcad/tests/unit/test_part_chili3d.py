#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'chili3d' part type: how it is wired, and that it actually renders.

The wiring tests run everywhere. The one that renders needs a Node.js and a
reachable npm registry - the same bargain the Python runtime tests make with
pip - so it is skipped when there is no Node.js to run it with.
"""

import asyncio
import shutil

import pytest

import partcad as pc
from partcad import factory, sandbox_versions
from partcad.part_factory_chili3d import PartFactoryChili3d, resolve_chili3d
from partcad.shape import PART_EXTENSION_MAPPING, UNEXPORTABLE_PART_TYPES
from partcad.user_config import UserConfig

EXAMPLE = "examples/produce_part_chili3d_primitive"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or shutil.which("npm") is None,
    reason="Chili3D renders in a Node.js sandbox; no node/npm on this host",
)


@pytest.fixture
def javascript_config():
    user_config = UserConfig()
    # 'none' uses the host's Node.js, which is what the skip above checked for.
    user_config.set("javascript_sandbox", "none")
    return user_config


def test_the_type_is_registered():
    assert factory.all["part"]["chili3d"] is PartFactoryChili3d


def test_a_chili3d_part_lives_in_a_chili_file():
    assert PART_EXTENSION_MAPPING["chili3d"] == "chili"


def test_chili3d_is_an_input_format_only():
    """Nothing in this repository writes a '.chili' file back out."""
    assert "chili3d" in UNEXPORTABLE_PART_TYPES


def test_the_example_declares_a_chili3d_part(javascript_config):
    ctx = pc.Context(EXAMPLE, user_config=javascript_config)
    part = ctx.get_part("cube")

    assert part.config["type"] == "chili3d"
    assert part.path.endswith("cube.chili")


def test_the_default_sandbox_is_the_default_node(javascript_config):
    ctx = pc.Context(EXAMPLE, user_config=javascript_config)

    ctx.get_part("cube")

    assert list(ctx.runtimes_javascript) == ["none-" + sandbox_versions.DEFAULT_NODE_VERSION]


def test_a_node_below_the_floor_is_raised_to_it(tmp_path, javascript_config):
    """The wrapper needs a Node.js new enough to load the way it loads.

    A package asking for an older one is rendered on the floor rather than
    failing during the wrapper's own bootstrap, which is where the CadQuery
    factory puts a package that asks for a Python CadQuery has no release for.
    """
    (tmp_path / "partcad.yaml").write_text(
        'javascriptVersion: "18"\n\nparts:\n  cube:\n    type: chili3d\n',
    )
    (tmp_path / "cube.chili").write_text("show(shapeFactory.box(chili3d.Plane.XY, 1, 1, 1).value);\n")
    ctx = pc.Context(str(tmp_path), user_config=javascript_config)

    ctx.get_part("cube")

    assert list(ctx.runtimes_javascript) == ["none-" + sandbox_versions.MIN_NODE_VERSION]


#
# Choosing versions
#


class _Project:
    """Just the package-level attributes resolve_chili3d() reads."""

    def __init__(self, chili3d_version=None):
        self.chili3d_version = chili3d_version


def test_the_default_chili3d_is_only_a_default():
    """So that a 'chili3d@...' in javascriptRequirements is left standing."""
    assert resolve_chili3d({}, _Project()) == (sandbox_versions.CHILI3D, True)


def test_a_package_can_choose_its_chili3d():
    requirement, is_default = resolve_chili3d({}, _Project("1.0.0"))

    assert requirement == "chili3d@1.0.0"
    assert is_default is False


def test_a_part_outranks_its_package():
    requirement, is_default = resolve_chili3d({"chili3dVersion": "1.0.1"}, _Project("1.0.0"))

    assert requirement == "chili3d@1.0.1"
    assert is_default is False


def test_a_part_requirement_outranks_the_package_version():
    """Same rule stated the other way: the more specific level wins.

    The declaration is left as a default so that the entry the part put in
    'javascriptRequirements' is the one that survives.
    """
    _, is_default = resolve_chili3d({"javascriptRequirements": ["chili3d@1.0.9"]}, _Project("1.0.0"))

    assert is_default is True


def test_the_dedicated_option_outranks_the_requirements_list():
    """Within one level, the specific knob beats the general one."""
    config = {"chili3dVersion": "1.0.1", "javascriptRequirements": ["chili3d@1.0.9"]}

    assert resolve_chili3d(config, _Project()) == ("chili3d@1.0.1", False)


def test_an_unrelated_requirement_does_not_count_as_choosing_chili3d():
    _, is_default = resolve_chili3d({"javascriptRequirements": ["seedrandom@3.0.5"]}, _Project("1.0.0"))

    assert is_default is False


def test_a_part_can_choose_its_node(tmp_path, javascript_config):
    (tmp_path / "partcad.yaml").write_text(
        'javascriptVersion: "22"\n\nparts:\n  cube:\n    type: chili3d\n    javascriptVersion: "24"\n',
    )
    (tmp_path / "cube.chili").write_text("show(shapeFactory.box(chili3d.Plane.XY, 1, 1, 1).value);\n")
    ctx = pc.Context(str(tmp_path), user_config=javascript_config)

    ctx.get_part("cube")

    assert list(ctx.runtimes_javascript) == ["none-24"]


def test_the_chosen_versions_are_part_of_the_cache_key(tmp_path, javascript_config):
    """Otherwise a version change would be served the previous version's shape."""

    def hash_of(chili3d_version):
        package = tmp_path / chili3d_version
        package.mkdir()
        (package / "partcad.yaml").write_text(
            'chili3dVersion: "%s"\n\nparts:\n  cube:\n    type: chili3d\n' % chili3d_version,
        )
        (package / "cube.chili").write_text("show(shapeFactory.box(chili3d.Plane.XY, 1, 1, 1).value);\n")
        ctx = pc.Context(str(package), user_config=javascript_config)
        return ctx.get_part("cube").hash.get()

    assert hash_of("1.0.0") != hash_of("1.0.1")


@needs_node
@pytest.mark.slow
def test_the_example_renders_to_a_brep_envelope(javascript_config):
    """End to end: a '.chili' script becomes the BREP the core carries.

    Deliberately checks the envelope rather than the geometry: the core never
    holds a live shape, and decoding one here would drag OCP into the test.
    """
    ctx = pc.Context(EXAMPLE, user_config=javascript_config)
    part = ctx.get_part("cube")

    shape = asyncio.run(part.get_wrapped(ctx))

    assert part.errors == []
    assert shape is not None
    assert "brep" in shape
    assert shape["label"] == "cube"
    # The script shows exactly one shape, so it is the only component.
    assert len(part.components) == 1
