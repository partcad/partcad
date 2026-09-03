#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The client's copy of PartCAD's object types, checked against the original.

`partcad_client.object_types` answers one question -- is this object already a
mesh? -- for `pc open`, in a process that must not `import partcad`: the client
is deliberately cheap, and a machine running `pc open` may have no CAD kernel on
it at all. So the type tables are inlined there, the way
`partcad_cli.click.commands.adhoc.convert.part` inlines the type lists it offers.

An inlined copy is only safe while something notices it drifting, and this is
that something. It fails by name when a part type is added to PartCAD and not
classified in the client, which matters more than it looks: an unclassified type
comes back as "not a mesh", which *works* -- the file is converted to STL and
Blender opens it -- so a new mesh format would silently take the slow, lossy
route and nothing would ever say so.

It lives here rather than beside the module it checks because this is the suite
that already has `partcad` in it; `tests/partcad_client` runs without one, and
that is worth keeping.
"""

from partcad import factory
from partcad.adhoc.adhoc import PACKAGE_ONLY_TYPES
from partcad.shape import PART_EXTENSION_MAPPING
from partcad_client import object_types

# Registering the part factories is `partcad.globals`' doing, and it happens on
# import; `partcad.factory.all` is empty without it.
import partcad.globals  # noqa: F401  isort:skip


def test_every_part_type_partcad_has_is_classified():
    """Every type a package may declare, and every type PartCAD writes."""
    expected = set(factory.all["part"]) | set(PART_EXTENSION_MAPPING)
    classified = set(object_types.PART_TYPE_IS_MESH)
    missing = sorted(expected - classified)
    assert not missing, (
        f"These PartCAD part types are not classified in partcad_client.object_types: {', '.join(missing)}. "
        "Add each one to PART_TYPE_IS_MESH with True when the file it names carries triangles and False "
        "when it does not. Leaving one out is not a no-op: `pc open --with blender` would convert it to "
        "STL first, which works and is wrong for a format Blender could have read as it is."
    )


def test_nothing_is_classified_that_partcad_does_not_have():
    """A stale entry is a type nobody can declare, and a reader's wild goose chase."""
    expected = set(factory.all["part"]) | set(PART_EXTENSION_MAPPING)
    extra = sorted(set(object_types.PART_TYPE_IS_MESH) - expected)
    assert not extra, (
        f"partcad_client.object_types classifies types PartCAD does not have: {', '.join(extra)}. "
        "Remove them, or restore them in partcad.globals if the removal was the mistake."
    )


def test_the_extension_of_each_type_is_the_one_partcad_uses():
    """The client infers a type from a file name; PartCAD decides what that name is."""
    assert object_types.PART_TYPE_EXTENSION == PART_EXTENSION_MAPPING


def test_the_types_that_only_mean_something_in_a_package_are_the_same_ones():
    """`pc open` refuses these by name instead of sending a conversion that is refused."""
    assert object_types.PACKAGE_ONLY_TYPES == PACKAGE_ONLY_TYPES


def test_the_extensions_that_are_other_spellings_name_types_that_exist():
    """'.stp' is a STEP file; a spelling that named nothing would silently mean nothing."""
    unknown = sorted(
        object_type
        for object_type in set(object_types.EXTENSION_ALIASES.values())
        if object_type not in object_types.PART_TYPE_IS_MESH
    )
    assert not unknown, f"EXTENSION_ALIASES maps to types that do not exist: {', '.join(unknown)}"
