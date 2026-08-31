#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import partcad as pc


def test_enumerate_shapes_all_null_sections():
    """`sketches:`/`parts:`/`assemblies:` present but null (as `pc init` writes
    them) must not crash shape enumeration.

    Regression: get_keys() used ``config_obj.get(name, {})``, which returns
    ``None`` for a key that exists with a null value, and then ``.keys()`` raised
    ``AttributeError: 'NoneType' object has no attribute 'keys'``.
    """
    ctx = pc.Context("tests/partcad/unit/data/enum_null_all.yaml")
    prj = ctx.get_project(pc.ROOT)
    assert prj._enumerate_shapes(None, None, None, None) == []


def test_enumerate_shapes_null_section_with_parts():
    """A null section next to a populated one still enumerates the populated one."""
    ctx = pc.Context("tests/partcad/unit/data/enum_null_mixed/partcad.yaml")
    prj = ctx.get_project(pc.ROOT)
    shapes = prj._enumerate_shapes(None, None, None, None)
    assert len(shapes) == 1


def test_enumerate_shapes_named_object_only():
    """Naming one object renders that object, not the whole package.

    Regression: every kind defaulted to "all of them" on its own, so naming a
    part enumerated it *and* every sketch and assembly beside it - a render of
    the whole package under the name of one object.
    """
    ctx = pc.Context("tests/partcad/unit/data/enum_named/partcad.yaml")
    prj = ctx.get_project(pc.ROOT)
    shapes = prj._enumerate_shapes(None, None, ["cube"], None)
    assert [shape.name for shape in shapes] == ["cube"]


def test_enumerate_shapes_nothing_named_is_the_whole_package():
    ctx = pc.Context("tests/partcad/unit/data/enum_named/partcad.yaml")
    prj = ctx.get_project(pc.ROOT)
    shapes = prj._enumerate_shapes(None, None, None, None)
    assert sorted(shape.name for shape in shapes) == ["circle", "cube", "logo"]
