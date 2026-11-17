#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An object's declaration written back out of the context, and 'pc copy' (see 'partcad.serialize').

What is pinned: that the declaration is what PartCAD read rather than the
file's text (a Jinja2 template is rendered, an override applied), that what is
only a default is left out, that the order is the declaration's own, and that a
copy into another package still refers to, and reads, what the original did.
"""

import os

import pytest
import yaml

import partcad as pc
from partcad import serialize
from partcad.actions.copy import copy_object_action

TEMPLATED = """name: //
parts:
{% for size in [10, 20] %}
  cube{{ size }}:
    type: basic
    desc: A cube of {{ size }}
    cuboid: {{ size }}
    manufacturable: true
{% endfor %}
  sized:
    type: basic
    parameters:
      width: 4
      depth:
        type: float
        default: 2.5
      count:
        type: int
        default: 3
        min: 1
    cuboid: 1
  alias:
    type: alias
    source: :cube10
  shell:
    type: step
  other_file:
    type: step
    path: files/elsewhere.step
assemblies:
  pair:
    type: assy
sketches:
  disc:
    type: basic
    circle: 5
"""


@pytest.fixture
def ctx(tmp_path):
    root = tmp_path / "pkg"
    (root / "files").mkdir(parents=True)
    (root / "partcad.yaml").write_text(TEMPLATED)
    (root / "shell.step").write_text("ISO-10303-21;\nEND-ISO-10303-21;\n")
    (root / "files" / "elsewhere.step").write_text("ISO-10303-21;\nEND-ISO-10303-21;\n")
    (root / "pair.assy").write_text(yaml.safe_dump({"links": [{"part": "cube10"}]}))
    (root / "other").mkdir()
    (root / "other" / "partcad.yaml").write_text("parts: {}\n")
    return pc.Context(str(root), search_root=False)


def test_a_templated_object_is_what_the_template_rendered_to(ctx):
    assert serialize.declaration(ctx.root, "part", "cube20") == {"type": "basic", "desc": "A cube of 20", "cuboid": 20}


def test_derived_fields_and_defaults_are_left_out(ctx):
    declared = serialize.declaration(ctx.root, "part", "cube10")
    assert "name" not in declared
    assert "orig_name" not in declared
    # The package's own, so said for nothing.
    assert "manufacturable" not in declared


def test_the_order_is_the_declaration_s(ctx):
    assert list(serialize.declaration(ctx.root, "part", "sized")) == ["type", "parameters", "cuboid"]


def test_a_parameter_is_written_in_its_shortest_form(ctx):
    parameters = serialize.declaration(ctx.root, "part", "sized")["parameters"]
    assert parameters["width"] == 4
    assert parameters["depth"] == 2.5
    # More than a type and a default: kept as declared.
    assert parameters["count"] == {"type": "int", "default": 3, "min": 1}


@pytest.mark.parametrize(
    "declared, compact",
    [
        ({"type": "int", "default": 3}, 3),
        ({"type": "float", "default": 2.5}, 2.5),
        ({"type": "string", "default": "x"}, "x"),
        ({"type": "bool", "default": False}, False),
        ({"type": "array", "default": [1, 2]}, [1, 2]),
        # A float written as an integer would read back as an int.
        ({"type": "float", "default": 3}, {"default": 3}),
        ({"type": "float", "default": 3.0, "min": 1}, {"default": 3.0, "min": 1}),
        ({"type": "int", "default": 3, "max": 9}, {"type": "int", "default": 3, "max": 9}),
    ],
)
def test_compact_parameter(declared, compact):
    assert serialize.compact_parameter(declared) == compact


def test_a_file_at_its_default_path_is_not_named(ctx):
    assert "path" not in serialize.declaration(ctx.root, "part", "shell")
    assert serialize.declaration(ctx.root, "part", "other_file")["path"] == "files/elsewhere.step"


def test_an_assy_file_s_own_manufacturing_method_is_a_default(ctx):
    assert serialize.declaration(ctx.root, "assembly", "pair") == {"type": "assy"}


def test_a_copy_under_another_name_names_the_original_s_file(ctx):
    declared = serialize.declaration(ctx.root, "part", "shell", ctx.root, "shell_copy")
    assert declared["path"] == "shell.step"


def test_a_copy_into_another_package_spells_out_what_it_refers_to(ctx):
    other = ctx.get_project("//other")

    alias = serialize.declaration(ctx.root, "part", "alias", other, "alias")
    shell = serialize.declaration(ctx.root, "part", "shell", other, "shell")

    assert alias["source"] == "//:cube10"
    assert shell["path"] == "../shell.step"


def test_an_object_the_package_does_not_declare_is_refused(ctx):
    with pytest.raises(ValueError):
        serialize.declaration(ctx.root, "part", "nothing")


def test_yaml_text_keeps_the_order():
    text = serialize.yaml_text("thing", {"type": "basic", "desc": "x", "offset": {"z": 1}})
    assert text.splitlines() == ["thing:", "  type: basic", "  desc: x", "  offset:", "    z: 1"]


# ---- pc copy ----------------------------------------------------------------


def test_copy_declares_the_object_under_the_new_name(ctx):
    # Into a package whose 'partcad.yaml' is plain YAML: a template is a file
    # 'pc add' cannot write into either, since it is not YAML until rendered.
    other = ctx.get_project("//other")

    result = copy_object_action(ctx.root, "part", "cube20", other, "big")

    assert result["written"] is True
    assert result["target"] == "//other:big"
    with open(other.config_path, "r", encoding="utf-8") as f:
        written = yaml.safe_load(f)
    assert written["parts"]["big"] == {"type": "basic", "desc": "A cube of 20", "cuboid": 20}
    assert list(written["parts"]["big"]) == ["type", "desc", "cuboid"]
    reloaded = pc.Context(os.path.dirname(other.config_path), search_root=False)
    assert reloaded.root.get_part("big").config["cuboid"] == 20


def test_copy_writes_nothing_on_a_dry_run(ctx):
    with open(ctx.root.config_path, "r", encoding="utf-8") as f:
        before = f.read()

    result = copy_object_action(ctx.root, "sketch", "disc", ctx.root, "disc2", dry_run=True)

    assert result["written"] is False
    assert result["declaration"] == "disc2:\n  type: basic\n  circle: 5\n"
    with open(ctx.root.config_path, "r", encoding="utf-8") as f:
        assert f.read() == before


@pytest.mark.parametrize("taken", ["cube10", "disc"])
def test_copy_refuses_a_name_the_package_uses(ctx, taken):
    with pytest.raises(ValueError):
        copy_object_action(ctx.root, "part", "cube20", ctx.root, taken, dry_run=True)


def test_copy_never_writes_into_a_revision(ctx):
    class Revision:
        name = "//@abc"

    with pytest.raises(ValueError):
        copy_object_action(ctx.root, "part", "cube20", Revision(), "x", dry_run=True)


def test_yaml_text_writes_a_location_on_one_line_and_text_as_a_block():
    text = serialize.yaml_text(
        "port",
        {"location": [[0, 0, 10], [0, 0, 1], 0], "desc": "two\nlines\n", "names": [str(n) for n in range(10)]},
    )

    assert "  location: [[0, 0, 10], [0, 0, 1], 0]" in text.splitlines()
    assert "  desc: |" in text.splitlines()
    assert "    two" in text.splitlines()
    # Too long to read on one line: an item a line.
    assert "    - '9'" in text.splitlines()
    assert yaml.safe_load(text)["port"]["desc"] == "two\nlines\n"
