#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Unit tests for OpenSCAD parameter handling in PartFactoryScad.

The command PartCAD builds for OpenSCAD is exercised here without running
OpenSCAD itself: the pure helpers that translate PartCAD 'parameters'/'method'
config into '-D' overrides and an injected module call are tested directly, and
an end-to-end render is attempted only when OpenSCAD is installed.
"""

import asyncio
import os
import shutil

import pytest

import partcad as pc
from partcad.part_factory_scad import (
    _build_define_args,
    _build_method_call,
    _build_render_args,
    _parameter_values,
    _scad_literal,
    _write_render_script,
)


def test_scad_literal_scalars():
    assert _scad_literal(10) == "10"
    assert _scad_literal(2.5) == "2.5"
    # bool is a subclass of int and must not render as its integer value
    assert _scad_literal(True) == "true"
    assert _scad_literal(False) == "false"
    assert _scad_literal(None) == "undef"


def test_scad_literal_strings_are_quoted_and_escaped():
    assert _scad_literal("hello") == '"hello"'
    assert _scad_literal('a"b\\c') == '"a\\"b\\\\c"'


def test_scad_literal_vectors():
    assert _scad_literal([1, 2, 3]) == "[1, 2, 3]"
    assert _scad_literal((1, "x", True)) == '[1, "x", true]'


def test_scad_literal_rejects_unsupported():
    with pytest.raises(ValueError):
        _scad_literal({"a": 1})


def test_parameter_values_reads_defaults_and_bare_values():
    config = {
        "parameters": {
            "width": {"type": "float", "default": 10},
            "count": 3,
        }
    }
    assert _parameter_values(config) == {"width": 10, "count": 3}


def test_parameter_values_missing_is_empty():
    assert _parameter_values({}) == {}


def test_build_define_args():
    values = {"width": 10, "label": "hi", "on": True}
    assert _build_define_args(values) == [
        "-D",
        "width=10",
        "-D",
        'label="hi"',
        "-D",
        "on=true",
    ]


def test_build_method_call():
    assert _build_method_call("box", {"w": 10, "h": 5}) == "box(w=10, h=5);"


def test_build_method_call_no_args():
    assert _build_method_call("part", {}) == "part();"


def test_write_render_script_appends_without_touching_source(tmp_path):
    source = tmp_path / "lib.scad"
    source.write_text("module box(s) { cube(s); }")  # no trailing newline

    rendered = _write_render_script(str(source), "box(s=5);")
    try:
        # The source file is left untouched.
        assert source.read_text() == "module box(s) { cube(s); }"
        # The render copy has the call appended on its own line.
        assert rendered != str(source)
        with open(rendered) as f:
            assert f.read() == "module box(s) { cube(s); }\nbox(s=5);\n"
    finally:
        os.unlink(rendered)


def test_build_render_args_no_params_renders_source_directly():
    args, tmp = _build_render_args("openscad", "/tmp/out.stl", "/pkg/cube.scad", {})
    assert tmp is None
    assert args == ["openscad", "--export-format", "binstl", "-o", "/tmp/out.stl", "/pkg/cube.scad"]


def test_build_render_args_params_become_define_overrides():
    config = {"parameters": {"size": {"default": 20}, "label": {"default": "x"}}}
    args, tmp = _build_render_args("openscad", "/tmp/out.stl", "/pkg/cube.scad", config)
    assert tmp is None
    assert args == [
        "openscad",
        "--export-format",
        "binstl",
        "-o",
        "/tmp/out.stl",
        "-D",
        "size=20",
        "-D",
        'label="x"',
        "/pkg/cube.scad",
    ]


def test_build_render_args_method_injects_call_into_temp_copy(tmp_path):
    source = tmp_path / "lib.scad"
    source.write_text("module box(w, h) { cube([w, h, 1]); }\n")
    config = {"method": "box", "parameters": {"w": {"default": 10}, "h": {"default": 5}}}

    args, tmp = _build_render_args("openscad", "/tmp/out.stl", str(source), config)
    try:
        # A throwaway copy is rendered, not the source, and without -D overrides.
        assert tmp is not None and tmp.endswith(".scad") and os.path.exists(tmp)
        assert "-D" not in args
        assert args[-1] == tmp
        assert args[:5] == ["openscad", "--export-format", "binstl", "-o", "/tmp/out.stl"]
        # The source is untouched; the copy has the module call appended.
        assert source.read_text() == "module box(w, h) { cube([w, h, 1]); }\n"
        with open(tmp) as f:
            assert f.read().endswith("box(w=10, h=5);\n")
    finally:
        os.unlink(tmp)


@pytest.mark.skipif(shutil.which("openscad") is None, reason="No OpenSCAD installed")
def test_parameterized_module_part_instantiates():
    """The example 'box' part is a module-only SCAD file rendered via 'method'."""
    ctx = pc.Context("examples/produce_part_openscad")
    part = ctx.get_part(":box")
    assert part is not None

    wrapped = asyncio.run(part.get_wrapped(ctx))
    assert wrapped is not None
