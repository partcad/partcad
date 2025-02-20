#!/usr/bin/env python3
#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-01-06
#
# Licensed under Apache License, Version 2.0.
#

import platform
import pytest
import tempfile

import partcad as pc


def test_render_svg_part_1():
    """Render a primitive shape to SVG"""
    ctx = pc.init("examples")
    prj = ctx.get_project("//produce_part_cadquery_primitive")
    cube = prj.get_part("cube")
    assert cube is not None
    try:
        cube.render_svg(ctx, project=prj)
    except Exception as e:
        assert False, "Valid render request caused an exception: %s" % e


def test_render_svg_assy_1():
    """Render a primitive shape to SVG"""
    ctx = pc.init("examples")
    prj = ctx.get_project("//produce_assembly_assy")
    assy = prj.get_assembly("logo")
    assert assy is not None
    try:
        assy.render_svg(ctx, project=prj)
    except Exception as e:
        assert False, "Valid render request caused an exception: %s" % e


def test_render_svg_assy_2():
    """Render a primitive shape to SVG"""
    ctx = pc.init("examples")
    prj = ctx.get_project("//produce_assembly_assy")
    assy = prj.get_assembly("logo_embedded")
    assert assy is not None
    try:
        assy.render_svg(ctx, project=prj)
    except Exception as e:
        assert False, "Valid render request caused an exception: %s" % e


def test_render_project():
    """Render an entire project"""
    if platform.system() == "Windows":
        pytest.skip("Rendering to PNG is not supported in Windows CI due to Cairo")
    ctx = pc.init("examples")
    prj = ctx.get_project("//feature_export")
    assert prj is not None
    output_dir = tempfile.mkdtemp()
    prj.render(output_dir=output_dir)
