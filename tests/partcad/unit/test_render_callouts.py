#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The callouts 'render_svg.py' writes on a picture, with the real kernel.

"Component names" and "Component prices" are one callout per component - a node
of 'shape_tree' that holds no other node - with its name over its price, pinned
to the middle of it; "Port names" and "Interface names" say whether the two port
overlays write their names. What is under test is what ends up in the request
the overlays are drawn from and on which layer, without a sandbox: the module is
loaded the way the sandbox loads it.
"""

import importlib.util
import os
import sys

import pytest

import partcad as pc
from partcad import output, render_overlay

RENDER_DIR = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.RENDER]]
WRAPPERS_DIR = os.path.join(os.path.dirname(os.path.abspath(pc.__file__)), "wrappers")

# Inside the 'partcad' namespace, for the reason 'test_render_projection.py'
# gives: coverage is traced by module name.
MODULE_NAME = "partcad.builtin.render.render_svg"


@pytest.fixture(scope="module")
def real_svg():
    saved_path = list(sys.path)
    sys.path.append(WRAPPERS_DIR)
    try:
        spec = importlib.util.spec_from_file_location(MODULE_NAME, os.path.join(RENDER_DIR, "render_svg.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path[:] = saved_path


@pytest.fixture(scope="module")
def tree(real_svg):
    """An assembly of two 10 mm cubes, the second placed 100 mm along X, as 'shape_tree' carries it."""
    import build123d as bd
    import ocp_serialize

    cube = bd.Box(10, 10, 10).wrapped

    def leaf(name, label, location=None):
        node = {"name": name, "label": label, ocp_serialize.KEY_BREP: b"", ocp_serialize.KEY_SHAPE: cube}
        if location is not None:
            node[ocp_serialize.KEY_LOCATION] = location
        return node

    return {
        "name": "//pkg:top",
        "label": None,
        ocp_serialize.KEY_ASSEMBLY: [
            leaf("//pkg:cube", "left"),
            leaf("//pkg:cube", "right", [[100, 0, 0], [0, 0, 1], 0]),
        ],
    }


def test_a_component_is_named_by_its_link_and_otherwise_by_its_object(real_svg):
    assert real_svg.component_name({"name": "//pkg:cube", "label": "left"}) == "left"
    # The object rendered on its own has no link: its name, without the package.
    assert real_svg.component_name({"name": "//pub/robotics:bolt", "label": None}) == "bolt"


def test_every_component_gets_a_callout_in_the_middle_of_it(real_svg, tree):
    found = real_svg._components({"shape_tree": tree, real_svg.COMPONENT_NAMES_KEY: True})

    assert [rows for rows, _middle in found] == [["left"], ["right"]]
    assert found[0][1] == pytest.approx((0, 0, 0), abs=1e-6)
    # Where the tree placed it, not where its own shape is.
    assert found[1][1] == pytest.approx((100, 0, 0), abs=1e-6)


def test_the_price_is_the_second_row_of_the_same_callout(real_svg, tree):
    request = {
        "shape_tree": tree,
        real_svg.COMPONENT_NAMES_KEY: True,
        real_svg.COMPONENT_PRICES_KEY: {"//pkg:cube": "1.50 USD"},
    }
    assert [rows for rows, _middle in real_svg._components(request)] == [["left", "1.50 USD"], ["right", "1.50 USD"]]


def test_with_only_prices_asked_a_component_nobody_quoted_gets_no_callout(real_svg, tree):
    request = {"shape_tree": tree, real_svg.COMPONENT_PRICES_KEY: {"//pkg:other": "2.00 USD"}}
    assert real_svg._components(request) == []
    # And asked for nothing, nothing at all.
    assert real_svg._components({"shape_tree": tree}) == []


def _overlay(real_svg, request):
    """The overlays as (layer, edge count), on a picture looked at from the front."""
    right, up = real_svg._camera_axes((0, -100, 0), (0, 0, 1), real_svg.LOOK_AT)
    layers = real_svg._overlay_edges(request, 110.0, right, up, (-5, -5, 105, 5))
    return {layer: len(edges) for layer, _color, edges in layers}


PORTS = [
    {
        "port": "mount",
        "interface": "//pkg:flange",
        "interface_label": "flange",
        "instance": None,
        "owner": None,
        "location": [[0, 0, 5], [0, 0, 1], 0],
    }
]


def test_a_ports_name_is_written_unless_it_is_switched_off(real_svg):
    named = _overlay(real_svg, {"ports": PORTS, "with_ports": True})
    quiet = _overlay(real_svg, {"ports": PORTS, "with_ports": True, real_svg.PORT_NAMES_KEY: False})

    # The marker is drawn either way; only the name and its leader go.
    assert 0 < quiet["Ports"] < named["Ports"]


def test_an_interfaces_name_is_written_unless_it_is_switched_off(real_svg):
    named = _overlay(real_svg, {"ports": PORTS, "with_interfaces": True})
    quiet = _overlay(real_svg, {"ports": PORTS, "with_interfaces": True, real_svg.INTERFACE_NAMES_KEY: False})

    assert named["Interfaces"] > 0
    assert quiet["Interfaces"] == 0


def test_the_callouts_are_drawn_on_a_layer_of_their_own(real_svg, tree):
    layers = _overlay(real_svg, {"shape_tree": tree, real_svg.COMPONENT_NAMES_KEY: True})

    assert layers["Components"] > 0
    assert layers["Ports"] == layers["Interfaces"] == 0


def test_the_renderer_and_the_core_name_the_callout_switches_alike(real_svg):
    for name in ("COMPONENT_NAMES_KEY", "COMPONENT_PRICES_KEY", "PORT_NAMES_KEY", "INTERFACE_NAMES_KEY"):
        assert getattr(real_svg, name) == getattr(render_overlay, name)
