#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import pytest
import shutil

import partcad as pc

test_config_local = {
    "name": "//primitive_local",
    "type": "local",
    "path": "examples/produce_part_cadquery_primitive",
}

test_config_git = {
    "name": "//primitive_git",
    "type": "git",
    "url": "https://github.com/partcad/partcad",
    "revision": "devel",
    "relPath": "examples/produce_part_cadquery_primitive",
}


def test_part_get_step_1():
    """Load a STEP part from a project by the part name"""
    ctx = pc.Context("examples/produce_part_step")
    repo1 = ctx.get_project(".")
    assert repo1 is not None
    bolt = repo1.get_part("bolt")
    assert bolt is not None
    wrapped = asyncio.run(bolt.get_wrapped(ctx))
    assert wrapped is not None


def test_part_get_step_2():
    """Load a STEP part from the context by the project and part names"""
    ctx = pc.Context("examples/produce_part_step")
    bolt = ctx.get_part(":bolt")
    assert bolt is not None

    wrapped = asyncio.run(bolt.get_wrapped(ctx))
    assert wrapped is not None


def test_part_get_brep_1():
    """Load a BREP part from a project by the part name"""
    ctx = pc.Context("examples/produce_part_brep")
    repo1 = ctx.get_project(".")
    assert repo1 is not None
    box = repo1.get_part("box")
    assert box is not None
    wrapped = asyncio.run(box.get_wrapped(ctx))
    assert wrapped is not None


def test_part_get_brep_2():
    """Load a BREP part from the context by the project and part names"""
    ctx = pc.Context("examples/produce_part_brep")
    box = ctx.get_part(":box")
    assert box is not None

    wrapped = asyncio.run(box.get_wrapped(ctx))
    assert wrapped is not None

def test_part_get_obj_1():
    """Load a OBJ part from a project by the part name"""
    ctx = pc.Context("examples/produce_part_obj")
    repo1 = ctx.get_project(".")
    assert repo1 is not None
    box = repo1.get_part("cube")
    assert box is not None
    wrapped = asyncio.run(box.get_wrapped(ctx))
    assert wrapped is not None


def test_part_get_obj_2():
    """Load a OBJ part from the context by the project and part names"""
    ctx = pc.Context("examples/produce_part_obj")
    box = ctx.get_part(":cube")
    assert box is not None

    wrapped = asyncio.run(box.get_wrapped(ctx))
    assert wrapped is not None


def test_part_get_stl():
    """Load a STL part"""
    ctx = pc.Context("examples/produce_part_stl")
    part = ctx.get_part(":cube")
    assert part is not None

    wrapped = asyncio.run(part.get_wrapped(ctx))
    assert wrapped is not None


def test_part_get_3mf():
    """Load a 3MF part"""
    ctx = pc.Context("examples/produce_part_3mf")
    part = ctx.get_part(":cube")
    assert part is not None

    wrapped = asyncio.run(part.get_wrapped(ctx))
    assert wrapped is not None


def test_part_get_scad():
    """Load an OpenSCAD part"""
    scad_path = shutil.which("openscad")
    if not scad_path is None:
        ctx = pc.Context("examples/produce_part_openscad")
        part = ctx.get_part(":cube")
        assert part is not None

        wrapped = asyncio.run(part.get_wrapped(ctx))
        assert wrapped is not None
    else:
        pytest.skip("No OpenSCAD installed")


def test_part_get_3():
    """Instantiate a project by a local import config and load a part"""
    ctx = pc.Context()  # Empty config
    _ = pc.ProjectFactoryLocal(ctx, None, test_config_local)
    cylinder = ctx.get_part("//primitive_local:cylinder")
    assert cylinder is not None
    wrapped = asyncio.run(cylinder.get_wrapped(ctx))
    assert wrapped is not None


# Note: The below test fails if there are braking changes in the way parts are
#       declared. Keep it this way so that the braking changes are conciously
#       force pushed.
def test_part_get_4():
    """Instantiate a project by a git import config and load a part"""
    ctx = pc.Context()  # Empty config
    factory = pc.ProjectFactoryGit(ctx, None, test_config_git)
    assert factory.project.path.endswith(test_config_git["relPath"])
    cube = factory.project.get_part("cube")
    assert cube is not None

    wrapped = asyncio.run(cube.get_wrapped(ctx))
    assert wrapped is not None


def test_part_lazy_loading():
    """Test for lazy loading of geometry data"""
    ctx = pc.Context()  # Empty config
    _ = pc.ProjectFactoryLocal(ctx, None, test_config_local)
    cylinder = ctx.get_part("//primitive_local:cylinder")
    assert cylinder._wrapped is None

    wrapped = asyncio.run(cylinder.get_wrapped(ctx))
    assert wrapped is not None


def test_part_aliases():
    """Test for part aliases"""
    ctx = pc.Context()  # Empty config
    _ = pc.ProjectFactoryLocal(ctx, None, test_config_local)
    # "box" is an alias for "cube"
    box = ctx.get_part("//primitive_local:box")
    assert box is not None
    assert box._wrapped is None

    wrapped = asyncio.run(box.get_wrapped(ctx))
    assert wrapped is not None


def test_part_example_cadquery_primitive():
    """Instantiate all parts from the example: part_cadquery_primitive"""
    ctx = pc.init("examples")
    cube = ctx.get_part("//produce_part_cadquery_primitive:cube")
    assert cube is not None
    cylinder = ctx.get_part("//produce_part_cadquery_primitive:cylinder")
    assert cylinder is not None

    wrapped = asyncio.run(cylinder.get_wrapped(ctx))
    assert wrapped is not None


def test_part_example_cadquery_logo():
    """Instantiate all parts from the example: part_cadquery_logo"""
    ctx = pc.init("examples")
    bone = ctx.get_part("//produce_part_cadquery_logo:bone")
    assert bone is not None
    head_half = ctx.get_part("//produce_part_cadquery_logo:head_half")
    assert head_half is not None

    wrapped = asyncio.run(head_half.get_wrapped(ctx))
    assert wrapped is not None


def test_part_example_build123d_primitive():
    """Instantiate all parts from the example: part_build123d_primitive"""
    ctx = pc.init("examples")
    cube = ctx.get_part("//produce_part_build123d_primitive:cube")
    assert cube is not None

    wrapped = ctx.get_part_shape("//produce_part_build123d_primitive:cube")
    assert wrapped is not None
