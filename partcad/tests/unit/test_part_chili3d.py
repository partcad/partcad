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
from partcad.part_factory_chili3d import PartFactoryChili3d
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
