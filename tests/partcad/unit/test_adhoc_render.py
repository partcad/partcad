#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for 'pc adhoc render' -- rendering a file that belongs to no package.

The rendering itself is the same machinery 'pc render' drives and is covered
there; what is new here is the ad-hoc half. Two things have to hold for it to
mean anything:

- the projections it offers are the ones PartCAD actually implements, since with
  no package there is nothing to declare a file type of one's own in, and
- the formats that only mean something inside a package are refused, pointing at
  the command that does have one.

None of it needs a sandbox.
"""

import pytest

import partcad as pc
from partcad import output
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
