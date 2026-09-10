#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import importlib
from unittest import mock

import pytest
from _pytest.outcomes import Skipped

import partcad as pc
from partcad.shape import (
    LIVE_OBJECT_PART_TYPES,
    SERIALIZED_PART_TYPES,
    SUPPORTED_PART_TYPES,
    TEXT_PART_TYPES,
)


def _cube():
    ctx = pc.init("examples")
    prj = ctx.get_project("//produce_part_cadquery_primitive")
    cube = prj.get_part("cube")
    assert cube is not None
    return ctx, cube


def _live_library(name):
    """Import a CAD library, or skip if this environment cannot give us one.

    PartCAD builds shapes in sandboxed runtimes and declares neither build123d
    nor CadQuery as a dependency of the wheel, so asking convert() for a live
    object of that flavour is an opt-in by a caller who already has the library.
    Here it means the test runs only where somebody has installed one.

    'pytest.importorskip' is not enough to say that. It turns a *missing module*
    into a skip and lets every other ImportError through, and "cadquery is not
    usable here" is one of those others: cadquery imports 'IVtkOCC_Shape' and
    'IVtkVTK_ShapeData' at module scope, and those exist only in the VTK-carrying
    'cadquery-ocp'. Where OCP is the 'cadquery-ocp-novtk' that build123d depends
    on -- which is the one 'pyproject.toml' names, and the only one a checkout is
    supposed to have -- the novtk package's '__init__' leaves them undefined and
    "import cadquery" dies on "cannot import name 'IVtkOCC_Shape'". That is this
    machine not having a library, not this library being broken, so it skips.
    """
    try:
        return importlib.import_module(name)
    except ImportError as e:
        pytest.skip("'%s' is not usable in this environment: %s" % (name, e))


def _assert_wraps_an_ocp_shape(obj):
    """A live object of either flavour is one OCP shape in a thin wrapper.

    Asserted through 'OCP.TopoDS.TopoDS_Shape', which is a class of
    'cadquery-ocp-novtk' -- the OCP distribution build123d pulls in and the only
    one this repository installs. Deliberately not through anything of
    'cadquery-ocp': that distribution differs from novtk by carrying VTK, the two
    own one 160 MB native module between them, and a test that reached for a
    VTK-only class would be a test asking for both to be installed.

    'wrapped is not None' was what this checked, and it passes just as well when
    convert() hands back the 1x1x1 box it uses as a carrier with somebody else's
    geometry in it.
    """
    from OCP.TopoDS import TopoDS_Shape

    assert obj is not None
    assert isinstance(obj.wrapped, TopoDS_Shape), type(obj.wrapped)


def test_convert_supported_types():
    """The supported set is derived from the extension mappings."""
    assert LIVE_OBJECT_PART_TYPES == {"build123d", "cadquery"}
    assert SERIALIZED_PART_TYPES == {
        "3mf",
        "brep",
        "dxf",
        "gltf",
        "iges",
        "obj",
        "step",
        "stl",
        "svg",
        "threejs",
    }
    # 'scad' is an input-only format, so it must not be offered
    assert "scad" not in SUPPORTED_PART_TYPES
    assert TEXT_PART_TYPES < SERIALIZED_PART_TYPES


def test_convert_unknown_type_raises():
    """An unknown part type is rejected with the list of supported ones."""
    _, cube = _cube()

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(cube.convert("no_such_format"))

    message = str(excinfo.value)
    assert "no_such_format" in message
    for part_type in ("build123d", "cadquery", "step", "stl"):
        assert part_type in message, message


def test_convert_input_only_type_raises():
    """A format PartCAD can only read is rejected with an explanation."""
    _, cube = _cube()

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(cube.convert("scad"))

    assert "OpenSCAD" in str(excinfo.value)


def test_convert_serialized_without_context_raises():
    """Serialized formats need a context to run the exporter runtime."""
    _, cube = _cube()

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(cube.convert("step"))

    assert "context" in str(excinfo.value)


def test_a_library_that_cannot_be_imported_is_a_skip():
    """The regression this helper exists for, since nothing else would catch it.

    'pytest.importorskip' skips on a missing module and re-raises every other
    ImportError, so the CadQuery tests *failed* on a checkout whose OCP was the
    novtk build -- reported as a broken conversion, in a file whose subject is
    conversion, when all it meant was that this machine has no usable CadQuery.
    """
    with mock.patch("importlib.import_module", side_effect=ImportError("cannot import name 'IVtkOCC_Shape'")):
        with pytest.raises(Skipped, match="IVtkOCC_Shape"):
            _live_library("cadquery")


@pytest.mark.slow
def test_convert_build123d():
    """The live-object path hands back a build123d object.

    This is the one that runs on a plain checkout: build123d needs only
    'cadquery-ocp-novtk', so the live-object machinery -- decode the BREP, put
    the shape in a wrapper of the asked-for flavour -- is covered here whether or
    not anything can import cadquery.
    """
    b3d = _live_library("build123d")
    ctx, cube = _cube()

    obj = asyncio.run(cube.convert("build123d", ctx))
    assert isinstance(obj, b3d.Solid)
    _assert_wraps_an_ocp_shape(obj)


@pytest.mark.slow
def test_convert_cadquery():
    """The live-object path hands back a CadQuery object."""
    cq = _live_library("cadquery")
    ctx, cube = _cube()

    obj = asyncio.run(cube.convert("cadquery", ctx))
    assert isinstance(obj, cq.Solid)
    _assert_wraps_an_ocp_shape(obj)


@pytest.mark.slow
def test_convert_step_returns_str():
    """A textual serialized format comes back as 'str', not a file path."""
    ctx, cube = _cube()

    data = asyncio.run(cube.convert("step", ctx))
    assert isinstance(data, str)
    assert data.startswith("ISO-10303-21")


@pytest.mark.slow
def test_convert_stl_returns_bytes():
    """A format that may be binary comes back as 'bytes'."""
    ctx, cube = _cube()

    data = asyncio.run(cube.convert("stl", ctx))
    assert isinstance(data, bytes)
    assert len(data) > 0


@pytest.mark.slow
def test_convert_leaves_no_temporary_file():
    """The temporary file used by the exporter must not survive the call."""
    import tempfile
    import os

    ctx, cube = _cube()

    before = set(os.listdir(tempfile.gettempdir()))
    asyncio.run(cube.convert("step", ctx))
    after = set(os.listdir(tempfile.gettempdir()))

    leaked = [name for name in after - before if name.startswith("partcad-convert-")]
    assert not leaked, leaked


@pytest.mark.slow
def test_get_build123d_still_works_but_warns():
    """The old accessor keeps working and reports itself as deprecated."""
    _live_library("build123d")
    ctx, cube = _cube()

    with pytest.deprecated_call():
        obj = asyncio.run(cube.get_build123d(ctx))
    _assert_wraps_an_ocp_shape(obj)


@pytest.mark.slow
def test_get_cadquery_still_works_but_warns():
    """The old accessor keeps working and reports itself as deprecated."""
    _live_library("cadquery")
    ctx, cube = _cube()

    with pytest.deprecated_call():
        obj = asyncio.run(cube.get_cadquery(ctx))
    _assert_wraps_an_ocp_shape(obj)
