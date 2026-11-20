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


# ---- what review found ------------------------------------------------------


def test_a_copy_keeps_manufacturable_where_the_destination_would_read_it_otherwise(tmp_path):
    root = tmp_path / "m"
    _dir = root / "made"
    _dir.mkdir(parents=True)
    (root / "partcad.yaml").write_text(
        yaml.safe_dump({"name": "//", "manufacturable": False, "parts": {"cube": {"type": "basic", "cuboid": 1}}})
    )
    (_dir / "partcad.yaml").write_text(yaml.safe_dump({"manufacturable": True, "parts": {}}))
    context = pc.Context(str(root), search_root=False)
    made = context.get_project("//made")

    # Not manufacturable in its own package, which says so for it; the copy
    # would be read as manufacturable in '//made' without the key.
    copied = serialize.declaration(context.root, "part", "cube", made, "cube")

    assert copied["manufacturable"] is False
    assert "manufacturable" not in serialize.declaration(context.root, "part", "cube")


def test_a_copy_of_software_into_another_package_names_the_original_file(tmp_path):
    root = tmp_path / "s"
    (root / "other").mkdir(parents=True)
    (root / "partcad.yaml").write_text(yaml.safe_dump({"name": "//", "software": {"fw": {"path": "fw.bin"}}}))
    (root / "fw.bin").write_bytes(b"\0")
    (root / "other" / "partcad.yaml").write_text("parts: {}\n")
    context = pc.Context(str(root), search_root=False)

    copied = serialize.declaration(context.root, "software", "fw", context.get_project("//other"), "fw")

    assert copied["path"] == "../fw.bin"


def test_an_assy_file_naming_its_parts_without_a_package_is_not_copied_into_another(ctx, tmp_path):
    other = ctx.get_project("//other")

    with pytest.raises(ValueError, match="relative to its own package"):
        serialize.declaration(ctx.root, "assembly", "pair", other, "pair")
    # Within its own package it is copied as ever.
    assert serialize.declaration(ctx.root, "assembly", "pair", ctx.root, "pair2")["path"] == "pair.assy"


def test_an_assy_file_naming_everything_in_full_is_copied_into_another(ctx):
    path = os.path.join(ctx.root.config_dir, "pair.assy")
    with open(path, "w", encoding="utf-8") as f:
        f.write(yaml.safe_dump({"links": [{"part": "cube10", "package": "//"}]}))

    copied = serialize.declaration(ctx.root, "assembly", "pair", ctx.get_project("//other"), "pair")

    assert copied["path"] == "../pair.assy"


def test_an_instance_is_its_declaration_with_the_values_as_defaults(ctx):
    copied = serialize.declaration(ctx.root, "part", "sized;width=7")

    assert copied["parameters"]["width"] == 7


# ---- the second review ------------------------------------------------------


def test_a_copy_of_raw_software_under_the_name_of_its_file_s_stem_keeps_the_file(tmp_path):
    # Raw software has no extension of its own: without 'path', 'boot' is the
    # file 'boot', not 'boot.bin'.
    root = tmp_path / "s"
    root.mkdir()
    (root / "partcad.yaml").write_text(yaml.safe_dump({"name": "//", "software": {"fw": {"path": "boot.bin"}}}))
    (root / "boot.bin").write_bytes(b"\0")
    context = pc.Context(str(root), search_root=False)

    assert serialize.declaration(context.root, "software", "fw", context.root, "boot")["path"] == "boot.bin"


def test_a_copy_names_a_file_its_type_would_not_find_by_the_new_name(tmp_path):
    # A 'step' part called 'shell' looks for 'shell.step', not 'shell.stp'.
    root = tmp_path / "p"
    root.mkdir()
    (root / "partcad.yaml").write_text(
        yaml.safe_dump({"name": "//", "parts": {"old": {"type": "step", "path": "shell.stp"}}}, sort_keys=False)
    )
    (root / "shell.stp").write_text("ISO-10303-21;\nEND-ISO-10303-21;\n")
    context = pc.Context(str(root), search_root=False)

    assert serialize.declaration(context.root, "part", "old", context.root, "shell")["path"] == "shell.stp"


def test_an_interface_instance_is_its_declaration_with_the_values_as_defaults(tmp_path):
    root = tmp_path / "i"
    root.mkdir()
    (root / "partcad.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "//",
                "interfaces": {
                    "hole": {
                        "ports": {"h": {"location": [[0, 0, 0], [0, 0, 1], 0]}},
                        "parameters": {"size": {"type": "float", "default": 3.0}},
                    }
                },
            },
            sort_keys=False,
        )
    )
    context = pc.Context(str(root), search_root=False)

    copied = serialize.declaration(context.root, "interface", "hole;size=4", context.root, "hole4")

    assert copied["parameters"]["size"] in (4, 4.0, {"type": "float", "default": 4.0})


def test_an_assy_file_of_a_revision_naming_the_revision_s_own_package_is_not_copied_out_of_it(tmp_path, monkeypatch):
    import pygit2

    root = tmp_path / "r"
    pygit2.init_repository(str(root))
    (root / "partcad.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "//",
                "parts": {"cube": {"type": "basic", "cuboid": 1}},
                "assemblies": {"pair": {"type": "assy"}},
            },
            sort_keys=False,
        )
    )
    # Written in full: today's '//' as far as the working tree goes, the
    # revision's own inside the revision.
    (root / "pair.assy").write_text(yaml.safe_dump({"links": [{"part": "cube", "package": "//"}]}))
    (root / "other").mkdir()
    (root / "other" / "partcad.yaml").write_text("parts: {}\n")
    repo = pygit2.Repository(str(root))
    repo.index.add_all()
    repo.index.write()
    signature = pygit2.Signature("Test", "test@example.com", 1_700_000_000, 0)
    sha = str(repo.create_commit("HEAD", signature, signature, "first", repo.index.write_tree(), []))
    context = pc.Context(str(root), search_root=False)
    monkeypatch.setattr(context.user_config, "internal_state_dir", str(tmp_path / "state"))
    at_first = context.get_project("//@" + sha)

    with pytest.raises(ValueError, match="that revision's"):
        serialize.declaration(at_first, "assembly", "pair", context.get_project("//other"), "pair")
    # The working tree's file says the same of today's '//', and is copied.
    assert serialize.declaration(context.root, "assembly", "pair", context.get_project("//other"), "pair")


def test_copy_refuses_a_name_declared_since_the_package_was_loaded(tmp_path):
    root = tmp_path / "late"
    root.mkdir()
    (root / "partcad.yaml").write_text(
        yaml.safe_dump({"name": "//", "sketches": {"disc": {"type": "basic", "circle": 5}}}, sort_keys=False)
    )
    context = pc.Context(str(root), search_root=False)
    with open(context.root.config_path, "a", encoding="utf-8") as f:
        f.write("  late:\n    type: basic\n    circle: 1\n")

    with pytest.raises(ValueError, match="could not be declared"):
        copy_object_action(context.root, "sketch", "disc", context.root, "late")
    assert "circle: 1" in open(context.root.config_path, encoding="utf-8").read()


# ---- the third review -------------------------------------------------------


def test_a_colour_instance_is_its_declaration_with_the_values_as_defaults(tmp_path):
    root = tmp_path / "c"
    root.mkdir()
    (root / "partcad.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "//",
                "colors": {
                    "tint": {"parameters": {"shade": {"type": "string", "default": "FF0000FF"}}, "rgba": "%shade%"}
                },
            },
            sort_keys=False,
        )
    )
    context = pc.Context(str(root), search_root=False)

    copied = serialize.declaration(context.root, "color", "tint;shade=00FF00FF", context.root, "green")

    assert copied["rgba"] == "00FF00FF"


def test_an_assy_link_s_material_that_names_another_one_in_the_copy_is_not_copied(ctx):
    path = os.path.join(ctx.root.config_dir, "pair.assy")
    with open(path, "w", encoding="utf-8") as f:
        f.write(yaml.safe_dump({"links": [{"part": "cube10", "package": "//", "params": {"material": ":steel"}}]}))

    with pytest.raises(ValueError, match="material: :steel"):
        serialize.declaration(ctx.root, "assembly", "pair", ctx.get_project("//other"), "pair")


def test_an_assy_link_s_material_named_in_full_is_copied(ctx):
    path = os.path.join(ctx.root.config_dir, "pair.assy")
    with open(path, "w", encoding="utf-8") as f:
        f.write(yaml.safe_dump({"links": [{"part": "cube10", "package": "//", "params": {"material": "//:steel"}}]}))

    assert serialize.declaration(ctx.root, "assembly", "pair", ctx.get_project("//other"), "pair")["path"] == (
        "../pair.assy"
    )
