#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for 'pc adhoc render' -- rendering a file that belongs to no package.

The rendering itself is the same machinery 'pc render' drives and is covered
there; what is new here is the ad-hoc half. Two things have to hold for it to
mean anything:

- the projections it offers are the ones PartCAD actually implements, since
  any other file type comes from a package named with '-e', and
- the formats that only mean something inside a package are refused, pointing at
  the command that does have one.

And what it takes that 'pc render' takes has to mean the same thing: a
parameter value is declared on the input with the type it is written in, a
package to read a file type from is imported into the throwaway package, and a
file nobody named is named after the input with its values, the way 'pc render'
names an instance's.

None of it needs a sandbox.
"""

from pathlib import Path

import pytest
import ruamel.yaml

import partcad as pc
from partcad import output
from partcad.adhoc import adhoc
from partcad.adhoc import render as adhoc_render
from partcad.shape import PART_EXTENSION_MAPPING, RENDER_EXTENSION_MAPPING, SERIALIZED_PART_TYPES

# What the thin CLI offers. Inlined there so it does not import the heavy
# partcad package; imported here so the copy cannot drift.
from partcad_cli.click.commands.adhoc.render.part import PART_TYPES as CLI_PART_INPUT_TYPES
from partcad_cli.click.commands.adhoc.render.part import RENDER_TYPES as CLI_PART_RENDER_TYPES
from partcad_cli.click.commands.adhoc.render.sketch import RENDER_TYPES as CLI_SKETCH_RENDER_TYPES

# --------------------------------------------------------------------------- #
# What can be written                                                         #
# --------------------------------------------------------------------------- #


def test_the_cli_offers_exactly_the_projections_that_can_be_rendered():
    assert sorted(CLI_PART_RENDER_TYPES) == sorted(adhoc_render.PART_RENDER_FORMATS)
    assert sorted(CLI_SKETCH_RENDER_TYPES) == sorted(adhoc_render.SKETCH_RENDER_FORMATS)


def test_the_projections_are_the_ones_with_a_known_extension():
    """The output type is inferred from the file name, so the two have to agree.

    'RENDER_EXTENSION_MAPPING' is what 'adhoc_render' reads in reverse to tell
    from 'out.png' which projection was asked for. A format offered but missing
    from it could be asked for by name and never inferred; one in the mapping but
    not offered would be inferred and then refused.
    """
    assert sorted(adhoc_render.PART_RENDER_FORMATS) == sorted(RENDER_EXTENSION_MAPPING)


def test_the_extensions_are_what_the_builtin_package_declares():
    """'//builtin/render' is what actually writes the files, so it decides.

    A drift here is a file written with one extension and looked for under
    another.
    """
    ctx = pc.init("examples")
    declared = output.builtin_formats(ctx, output.RENDER)
    for format_name, extension in RENDER_EXTENSION_MAPPING.items():
        assert declared[format_name]["extension"] == extension, format_name


def test_a_projection_is_still_not_a_part_type():
    """Widening the render mapping must not make 'convert()' offer a picture.

    A projection cannot be read back in as a part, which is why the render
    formats are a mapping of their own rather than an entry in the part types.
    """
    for format_name in ("png", "jpeg"):
        assert format_name not in PART_EXTENSION_MAPPING
        assert format_name not in SERIALIZED_PART_TYPES


# --------------------------------------------------------------------------- #
# What cannot be rendered ad-hoc                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("input_type", ["urdf", "assy"])
def test_an_assembly_format_is_refused_and_points_at_the_package_command(tmp_path, input_type):
    """Neither means anything without the package its contents are named in."""
    source = tmp_path / ("robot.%s" % input_type)
    source.write_text("<robot name='r'><link name='a'/></robot>")

    with pytest.raises(ValueError) as excinfo:
        adhoc_render.render_cad_file(str(source), input_type, str(tmp_path / "out.png"), "png")

    message = str(excinfo.value)
    assert "only means anything inside a package" in message
    # The advice is the render one, not the conversion one: the user asked for a
    # picture, so 'pc convert assembly' is not what they want next.
    assert "pc render" in message
    assert "Cannot render from" in message


def test_the_cli_accepts_every_part_type_as_input():
    """A projection can be made of anything PartCAD can read, including the
    scripted types it cannot write back out -- 'sdf', 'scad' and 'chili3d' are
    input-only for a conversion but perfectly renderable."""
    for input_only in ("sdf", "scad", "chili3d"):
        assert input_only in CLI_PART_INPUT_TYPES


# --------------------------------------------------------------------------- #
# What 'pc render' takes, ad hoc                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text, declared",
    [
        ("true", {"type": "bool", "default": True}),
        ("False", {"type": "bool", "default": False}),
        ("12", {"type": "int", "default": 12}),
        ("-3", {"type": "int", "default": -3}),
        ("6.5", {"type": "float", "default": 6.5}),
        ("1e3", {"type": "float", "default": 1000.0}),
        ("M4", {"type": "string", "default": "M4"}),
        # Python reads these as numbers; nobody writing them means one.
        ("nan", {"type": "string", "default": "nan"}),
        ("inf", {"type": "string", "default": "inf"}),
        ("", {"type": "string", "default": ""}),
        (["10", "20.5"], {"type": "array", "default": [10, 20.5]}),
    ],
)
def test_a_value_is_declared_with_the_type_it_is_written_in(text, declared):
    assert adhoc.declare_parameter(text) == declared


def _config(tmp_path, **options):
    adhoc.generate_partcad_config(tmp_path, "build123d", tmp_path / "bracket's.py", **options)
    return ruamel.yaml.YAML(typ="safe").load((tmp_path / "partcad.yaml").read_text(encoding="utf-8"))


def test_the_throwaway_package_declares_the_input_alone_by_default(tmp_path):
    assert _config(tmp_path) == {"parts": {"input_part": {"type": "build123d", "path": str(tmp_path / "bracket's.py")}}}


def test_the_values_are_declared_on_the_input(tmp_path):
    config = _config(tmp_path, parameters={"depth": "12", "label": "M4: 'hex'"})

    assert config["parts"]["input_part"]["parameters"] == {
        "depth": {"type": "int", "default": 12},
        "label": {"type": "string", "default": "M4: 'hex'"},
    }


def test_the_package_to_read_a_file_type_from_is_imported(tmp_path):
    (tmp_path / "opts").mkdir()
    (tmp_path / "opts" / "partcad.yaml").write_text("render: {}\n", encoding="utf-8")
    dependency, name = adhoc.options_dependency(str(tmp_path / "opts"))

    config = _config(tmp_path, dependencies=dict([dependency]))

    assert name == "//options"
    assert config["dependencies"] == {"options": {"type": "local", "path": str((tmp_path / "opts").resolve())}}


def test_a_package_of_the_public_index_is_imported_the_way_pc_init_imports_the_index():
    """The same declaration as a new package's, so that the importer treats it the same way."""
    (name, declaration), package = adhoc.options_dependency("//pub/feature/render/draftwright")
    template = Path(output.__file__).parent / "template" / "init-public.yaml"
    pub = ruamel.yaml.YAML(typ="safe").load(template.read_text(encoding="utf-8"))["dependencies"]["pub"]

    assert (name, package) == ("pub", "//pub/feature/render/draftwright")
    assert declaration == pub


@pytest.mark.parametrize("named", ["//elsewhere/render", "no/such/directory"])
def test_a_package_an_ad_hoc_render_cannot_reach_is_refused(named):
    with pytest.raises(adhoc.AdhocUsageError) as excinfo:
        adhoc.options_dependency(named)
    assert "//pub/" in str(excinfo.value)


def test_a_directory_with_no_package_in_it_is_refused(tmp_path):
    with pytest.raises(adhoc.AdhocUsageError):
        adhoc.options_dependency(str(tmp_path))


def test_no_package_imports_nothing():
    assert adhoc.options_dependency(None) == (None, None)


@pytest.mark.parametrize(
    "parameters, extension, name",
    [
        (None, ".svg", "bracket.svg"),
        ({"depth": "12", "hole": "6.5"}, ".svg", "bracket_depth_12_hole_6.5.svg"),
        # Sorted by name, as 'pc render' writes an instance's, whatever order they came in.
        ({"hole": "6.5", "depth": "12"}, ".thin.svg", "bracket_depth_12_hole_6.5.thin.svg"),
        ({"medium": "//pub/std:air"}, ".png", "bracket_medium_pub_std_air.png"),
    ],
)
def test_a_file_nobody_named_is_named_after_the_input_and_its_values(tmp_path, parameters, extension, name):
    assert adhoc.default_output_name(tmp_path / "bracket.py", parameters, extension) == name


def test_the_values_are_written_into_a_name_as_pc_render_writes_them():
    """One rule for both: what an object's instance is called on disk, and what an ad-hoc file of it is."""
    values = {"length": "10", "size": "M4"}
    assert output.name_to_segments("bolt;length=10,size=M4") == ["bolt" + output.values_in_file_name(values)]
    assert output.values_in_file_name({}) == ""
    assert output.values_in_file_name(values) == "_length_10_size_M4"
