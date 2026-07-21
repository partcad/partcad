#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

import pytest

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


@pytest.mark.slow
def test_convert_build123d():
    """The live-object path hands back a build123d object."""
    # PartCAD builds shapes in sandboxed runtimes, so neither build123d nor
    # CadQuery is guaranteed to be importable in this process. Asking convert()
    # for a live object of that flavour is an explicit opt-in by the caller.
    pytest.importorskip("build123d")
    ctx, cube = _cube()

    obj = asyncio.run(cube.convert("build123d", ctx))
    assert obj is not None
    assert obj.wrapped is not None


@pytest.mark.slow
def test_convert_cadquery():
    """The live-object path hands back a CadQuery object."""
    pytest.importorskip("cadquery")
    ctx, cube = _cube()

    obj = asyncio.run(cube.convert("cadquery", ctx))
    assert obj is not None
    assert obj.wrapped is not None


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
    pytest.importorskip("build123d")
    ctx, cube = _cube()

    with pytest.deprecated_call():
        obj = asyncio.run(cube.get_build123d(ctx))
    assert obj is not None
    assert obj.wrapped is not None


@pytest.mark.slow
def test_get_cadquery_still_works_but_warns():
    """The old accessor keeps working and reports itself as deprecated."""
    pytest.importorskip("cadquery")
    ctx, cube = _cube()

    with pytest.deprecated_call():
        obj = asyncio.run(cube.get_cadquery(ctx))
    assert obj is not None
    assert obj.wrapped is not None
