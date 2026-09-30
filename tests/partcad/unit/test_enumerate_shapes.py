#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

import partcad as pc
from partcad.project import Project


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


def test_enumerate_shapes_awaits_a_part_that_has_to_be_materialized():
    """A part named '<assembly>/<link>' is built rather than refused.

    'pc export //pkg:robot/base_link' resolves that part from inside
    'Project.render_async()', which is a coroutine -- and the synchronous
    'get_part()' refuses there by design, because materializing such a part
    means instantiating the assembly that produces it, which is asynchronous
    (see 'test_derived_part_materialization.py'). So the enumeration awaits
    'get_part_async()', and asking for a derived part by name used to end in
    "cannot materialize the derived part ... from a coroutine" instead of a
    file.
    """
    prj = Project.__new__(Project)
    asked = []
    shape = object()

    def get_part(name, *args, **kwargs):
        raise AssertionError("the synchronous accessor cannot serve a coroutine")

    async def get_part_async(name, *args, **kwargs):
        asked.append(name)
        return shape

    prj.get_part = get_part
    prj.get_part_async = get_part_async
    prj.get_sketch = get_part
    prj.get_assembly = get_part
    prj.get_scene = get_part

    async def main():
        return await prj._enumerate_shapes_async(None, None, ["robot/base_link"], None)

    assert asyncio.run(main()) == [shape]
    assert asked == ["robot/base_link"]
