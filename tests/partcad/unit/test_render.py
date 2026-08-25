#!/usr/bin/env python3
#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-01-06
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import copy
import os
import platform
import pytest
import tempfile

import partcad as pc

# A package whose top level assembly is built out of another package's parts and
# assemblies, so that the grouping and the counting have something to group and
# count that the examples do not cover.
ASSEMBLY_BOM_PACKAGE = "tests/partcad/unit/data/assembly_bom/partcad.yaml"


@pytest.mark.slow
def test_render_svg_part_1():
    """Render a primitive shape to SVG"""
    ctx = pc.init("examples")
    prj = ctx.get_project("//produce_part_cadquery_primitive")
    cube = prj.get_part("cube")
    assert cube is not None
    try:
        # cube.render_svg(ctx, project=prj)
        cube.render(ctx, "svg", prj)
    except Exception as e:
        assert False, "Valid render request caused an exception: %s" % e


@pytest.mark.slow
def test_render_svg_assy_1():
    """Render a primitive shape to SVG"""
    ctx = pc.init("examples")
    prj = ctx.get_project("//produce_assembly_assy")
    assy = prj.get_assembly("logo")
    assert assy is not None
    try:
        # assy.render_svg(ctx, project=prj)
        assy.render(ctx, "svg", prj)
    except Exception as e:
        assert False, "Valid render request caused an exception: %s" % e


@pytest.mark.slow
def test_render_svg_assy_2():
    """Render a primitive shape to SVG"""
    ctx = pc.init("examples")
    prj = ctx.get_project("//produce_assembly_assy")
    assy = prj.get_assembly("logo_embedded")
    assert assy is not None
    try:
        # assy.render_svg(ctx, project=prj)
        assy.render(ctx, "svg", prj)
    except Exception as e:
        assert False, "Valid render request caused an exception: %s" % e


@pytest.mark.slow
def test_render_project():
    """Render an entire project

    'feature_render' rather than 'feature_export': it is the example that
    declares every 2D target, which is what makes this cover more than one
    implementation. (The 3D and CAD files moved to 'feature_export' and its
    'export:' section.)
    """
    if platform.system() == "Windows":
        pytest.skip("Rendering to PNG is not supported in Windows CI due to Cairo")
    ctx = pc.init("examples")
    prj = ctx.get_project("//feature_render")
    assert prj is not None
    output_dir = tempfile.mkdtemp()
    prj.render(output_dir=output_dir)


def test_assembly_bom_grouped():
    """The contents of an assembly, grouped by package and counted"""
    ctx = pc.init("examples")
    assy = ctx._get_assembly("//produce_assembly_assy:logo_embedded")
    assert assy is not None
    grouped = asyncio.run(assy.get_bom_grouped_async())

    parts = grouped["parts"]
    assert sorted(parts.keys()) == [
        "//pub/examples/partcad/produce_part_cadquery_logo",
        "//pub/examples/partcad/produce_part_step",
    ]
    logo_parts = parts["//pub/examples/partcad/produce_part_cadquery_logo"]
    assert logo_parts["bone"]["count"] == 2
    assert logo_parts["head_half"]["count"] == 2
    assert logo_parts["bone"]["desc"] == "Plate used as one of the bones on PartCAD logo"
    assert parts["//pub/examples/partcad/produce_part_step"]["bolt"]["count"] == 1

    # The assembly embedded in 'logo_embedded.assy' is not an object of any
    # package, so it contributes its parts instead of being listed itself.
    assert grouped["assemblies"] == {}


def test_render_assembly_readme():
    """Export an assembly to a markdown document"""
    ctx = pc.init("examples")
    prj = ctx.get_project("//produce_assembly_assy")
    assert prj is not None
    output_dir = tempfile.mkdtemp()
    prj.render(assemblies=["logo_embedded"], format="readme", output_dir=output_dir)

    # The requested assembly is the subject of the document, so the package
    # document is not generated.
    assert not os.path.exists(os.path.join(output_dir, "README.md"))

    with open(os.path.join(output_dir, "logo_embedded.md")) as f:
        lines = f.read().splitlines()

    assert lines[0] == "# logo_embedded"
    assert "PartCAD logo using embedded assemblies" in lines
    assert "## Parts" in lines
    assert "### //pub/examples/partcad/produce_part_cadquery_logo" in lines
    assert "| Part | Count | Description |" in lines
    assert "| bone | 2 | Plate used as one of the bones on PartCAD logo |" in lines
    assert "| head_half | 2 | Bracket used as one side of the head on PartCAD logo |" in lines
    assert "| bolt | 1 | M8x30-screw |" in lines
    # No sub-assembly of this assembly is an object of a package.
    assert "## Sub-Assemblies" not in lines


def test_render_assembly_readme_from_config():
    """An assembly asks for a document of its own in the package configuration"""
    ctx = pc.init("examples")
    prj = ctx.get_project("//produce_assembly_assy")
    assert prj is not None
    output_dir = tempfile.mkdtemp()
    prj.render(format="readme", output_dir=output_dir)

    assert os.path.exists(os.path.join(output_dir, "README.md"))
    assert os.path.exists(os.path.join(output_dir, "logo.md"))
    # Only the assemblies that ask for one get a document of their own.
    assert not os.path.exists(os.path.join(output_dir, "logo_embedded.md"))


def test_assembly_bom_grouped_sub_assemblies():
    """A sub-assembly declared by a package is counted as itself and walked into"""
    ctx = pc.Context(ASSEMBLY_BOM_PACKAGE)
    top = ctx._get_assembly("//:top")
    assert top is not None
    grouped = asyncio.run(top.get_bom_grouped_async())

    # 'top' uses '//sub:unit' twice, and each of those is a pair of cubes, on top
    # of the one cube 'top' places itself.
    assert grouped["assemblies"] == {"//sub": {"unit": {"count": 2, "desc": "A pair of cubes"}}}
    assert grouped["parts"] == {"//sub": {"cube": {"count": 5, "desc": "A cube"}}}


def test_render_assembly_readme_sub_assemblies():
    """The assembly document groups sub-assemblies by package and counts them"""
    ctx = pc.Context(ASSEMBLY_BOM_PACKAGE)
    prj = ctx.get_project("//")
    assert prj is not None
    output_dir = tempfile.mkdtemp()
    path = prj.render_assembly_readme("top", output_dir=output_dir)

    with open(path) as f:
        lines = f.read().splitlines()

    assert lines[0] == "# top"
    assert "## Sub-Assemblies" in lines
    assert "| Assembly | Count | Description |" in lines
    assert "| unit | 2 | A pair of cubes |" in lines
    assert "## Parts" in lines
    assert "| cube | 5 | A cube |" in lines
    # The document is generated outside of the package's own tree, so the
    # packages it refers to are named but not linked.
    assert "### //sub" in lines


def test_render_assembly_readme_keeps_package_config_intact():
    """Resolving one assembly's render settings does not mutate the package's"""
    ctx = pc.Context(ASSEMBLY_BOM_PACKAGE)
    prj = ctx.get_project("//")
    assert prj is not None
    before = copy.deepcopy(prj.config_obj["render"])
    assert before["svg"]["prefix"] == "./"

    prj.render_assembly_readme("top", output_dir=tempfile.mkdtemp())

    # 'top' overrides the SVG prefix; that override belongs to 'top' alone.
    assert prj.config_obj["render"] == before
