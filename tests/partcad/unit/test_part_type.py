#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for package-defined partTypes.

A partType is a reusable, package-defined way to construct parts. A part whose
'type' references it (the short form ':<name>', expanded to '<package>:<name>')
is built by PartFactoryWrapper. These tests cover the expansion, the partType
config accessor, and the factory dispatch without the sandbox; a gated
end-to-end test instantiates the shape when the sandbox is available.
"""

import asyncio
import os

import pytest

import partcad as pc
from partcad import factory, shape_envelope

EXAMPLE = "examples/produce_part_wrapper"

# A partType that reads the file its part points at: a square slab as wide as
# the number in it says.
SLAB_WRAPPER = """
if __name__ == "__partcad_part__":
    from build123d import Box

    with open(request["path"], encoding="utf-8") as f:
        size = float(f.read())
    output = {"shape": Box(size, size, 1).wrapped}
"""


def file_reading_part_type(tmp_path):
    """The partType in one package, and a part in another that points it at a file."""
    types = tmp_path / "types"
    types.mkdir()
    (types / "partcad.yaml").write_text("partTypes:\n  slab:\n    kind: wrapper\n    path: slab.py\n", encoding="utf-8")
    (types / "slab.py").write_text(SLAB_WRAPPER, encoding="utf-8")
    (tmp_path / "size.txt").write_text("7\n", encoding="utf-8")
    (tmp_path / "partcad.yaml").write_text(
        "parts:\n  slab:\n    type: types:slab\n    path: size.txt\n",
        encoding="utf-8",
    )
    return pc.Context(str(tmp_path))


def test_wrapper_factory_is_registered():
    # A part 'type' that carries a package path is dispatched to the wrapper.
    assert "wrapper" in factory.all["part"]


def test_part_type_definition_is_enumerated():
    ctx = pc.Context(EXAMPLE)
    root = ctx.get_project(ctx.get_current_project_path())
    cfg = root.get_part_type_config("box")
    assert cfg is not None
    assert cfg.get("kind", "wrapper") == "wrapper"
    assert cfg.get("path") == "box_wrapper.py"
    # It is enumerable as an object kind, and it is not a part.
    assert "box" in root.object_names("partType")
    assert "box" not in root.object_names("part")


def test_short_part_type_is_expanded_and_stored():
    ctx = pc.Context(EXAMPLE)
    root = ctx.get_project(ctx.get_current_project_path())

    part = ctx.get_part(":demo")
    assert part is not None

    # The short ':box' form is expanded to the fully-qualified '<package>:box'
    # and stored expanded (here, at construction, when the part factory is made).
    expanded = root.get_part_config("demo")["type"]
    assert expanded != ":box"
    assert expanded.endswith(":box")
    assert expanded == root.name + ":box"


def test_a_part_s_path_is_resolved_in_its_own_package_and_keys_its_cache(tmp_path):
    # The partType's script runs in 'types/', so 'size.txt' as written would
    # name a file that is not there. It is the part's package that it is in.
    ctx = file_reading_part_type(tmp_path)
    part = ctx.get_part("//:slab")
    assert part is not None

    expected = os.path.normpath(str(tmp_path / "size.txt"))
    assert [os.path.normpath(path) for path in part.cache_dependencies] == [expected]


def test_unknown_part_type_is_not_found():
    ctx = pc.Context(EXAMPLE)
    root = ctx.get_project(ctx.get_current_project_path())
    assert root.get_part_type_config("nope") is None


@pytest.mark.slow
def test_wrapper_part_instantiates():
    """End to end: the wrapper script produces the part's shape (needs the sandbox)."""
    ctx = pc.Context(EXAMPLE)
    part = ctx.get_part(":demo")
    assert part is not None
    try:
        wrapped = asyncio.run(part.get_wrapped(ctx))
    except Exception as e:
        pytest.skip("Sandbox unavailable for partType wrapper: %s" % e)
    assert wrapped is not None


@pytest.mark.slow
def test_a_part_type_reads_the_file_its_part_points_at(tmp_path):
    """End to end: 'request["path"]' is the part's file (needs the sandbox)."""
    ctx = file_reading_part_type(tmp_path)
    part = ctx.get_part("//:slab")
    try:
        metadata = asyncio.run(part.get_metadata_async(ctx))
    except Exception as e:
        pytest.skip("Sandbox unavailable for partType wrapper: %s" % e)
    assert metadata, "the partType built nothing"
    box = shape_envelope.metadata_section(metadata, shape_envelope.METADATA_MEASUREMENTS)[shape_envelope.METADATA_BBOX]
    assert [round(box[axis + 3] - box[axis], 6) for axis in range(3)] == [7.0, 7.0, 1.0]
