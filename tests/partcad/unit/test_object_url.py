#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Every object, and every declaration a package makes, may say where to read about it: 'url'."""

import textwrap

import jsonschema
import pytest
import yaml

import partcad as pc
from partcad import output
from partcad.lint.all import get_partcad_schema

PAGE = "https://www.example.com/hub"

PACKAGE = """
url: https://www.example.com/
parts:
  block:
    type: basic
    cuboid: 10
    url: https://www.example.com/block
  plain:
    type: basic
    cuboid: 10
assemblies:
  hub:
    type: assy
    url: https://www.example.com/hub
interfaces:
  mount:
    url: https://www.example.com/mount
    ports:
      top: [[0, 0, 0], [0, 0, 1], 0]
sketches:
  ring:
    type: basic
    circle: 5
    url: https://www.example.com/ring
scenes:
  bench:
    type: assy
    url: https://www.example.com/bench
partTypes:
  widget:
    kind: wrapper
    path: widget.py
    url: https://www.example.com/widget
providers:
  shop:
    type: store
    path: shop.py
    url: https://www.example.com/shop
repositories:
  catalog:
    type: basic
    path: catalog.py
    url: https://www.example.com/catalog
import:
  fmt:
    path: read_fmt.py
    url: https://www.example.com/fmt
render:
  pretty:
    path: pretty.py
    url: https://www.example.com/pretty
export:
  thing:
    path: thing.py
    url: https://www.example.com/thing
simulation:
  sim:
    path: sim.py
    url: https://www.example.com/sim
open:
  viewer:
    desc: A viewer
    url: https://www.example.com/viewer
"""


def test_the_schema_takes_it_on_every_kind_of_declaration():
    jsonschema.validate(yaml.safe_load(PACKAGE), get_partcad_schema())


@pytest.mark.parametrize("kind, name", [("assemblies", "hub"), ("interfaces", "mount"), ("sketches", "ring")])
def test_the_schema_refuses_one_that_is_not_a_url(kind, name):
    document = yaml.safe_load(PACKAGE)
    document[kind][name]["url"] = "not a url"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, get_partcad_schema())


def test_a_plugin_is_never_handed_it():
    implementation = output.Implementation("render", "pretty", {"path": "pretty.py", "url": PAGE, "size": 3})
    assert implementation.parameters == {"size": 3}


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "partcad.yaml").write_text(textwrap.dedent(PACKAGE))
    (tmp_path / "hub.assy").write_text("links:\n  - part: block\n")
    (tmp_path / "bench.assy").write_text("links:\n  - part: block\n")
    return pc.Context(str(tmp_path))


def test_info_says_an_object_s_own_and_else_its_package_s(ctx):
    block, plain = ctx.get_part(":block"), ctx.get_part(":plain")
    assert block.info()["Url"] == "https://www.example.com/block"
    assert plain.info()["Url"] == "https://www.example.com/"
    assert ctx.get_assembly(":hub").info()["Url"] == PAGE
    assert ctx.get_sketch(":ring").info()["Url"] == "https://www.example.com/ring"


def test_info_says_an_interface_s(ctx):
    assert ctx.get_interface(":mount").info()["url"] == "https://www.example.com/mount"
