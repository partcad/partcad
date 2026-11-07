#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part keyed on the files its part type reported reading the last time it was built.

The list, its key and its hash are checked on their own; and a package's own
part type - a '.box' file that names the file holding its size - is built,
the size edited, and built again in a fresh context: a part type that reports
the file is built anew, one that does not is read back from the cache, as a
part whose files nobody knew of always was.
"""

import asyncio
import importlib
import os
import sys
import uuid

import pytest
import yaml

import partcad as pc
from partcad import discovered_dependencies
from partcad.cache_hash import CacheHash

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))


# ---------------------------------------------------------------------------
# The list and the key
# ---------------------------------------------------------------------------


def test_a_list_is_relative_to_the_part_s_file_where_under_it_sorted_and_each_once(tmp_path):
    base = tmp_path / "pkg"
    outside = os.path.abspath(str(tmp_path / "elsewhere" / "wood.png"))
    reported = [
        "layers/geom.usda",
        str(base / "layers" / "geom.usda"),
        str(base / "stage.usda"),
        outside,
        "",
        7,
        "./textures/../textures/a.png",
    ]
    listed = discovered_dependencies.normalized(reported, str(base), own=str(base / "stage.usda"))
    assert listed == sorted(["layers/geom.usda", "textures/a.png", outside])
    assert discovered_dependencies.normalized("not a list", str(base)) == []
    assert discovered_dependencies.resolved(listed, str(base)) == [
        os.path.normpath(p)
        for p in sorted([str(base / "layers" / "geom.usda"), str(base / "textures" / "a.png"), outside])
    ]


def test_a_kept_list_reads_back_as_it_was_written_and_anything_else_as_none():
    listed = ["a.usda", "b/c.png"]
    assert discovered_dependencies.parse(discovered_dependencies.serialize(listed)) == listed
    for bad in (None, b"", b"not json", b'{"files": "a"}', b'{"files": [1]}', b"[1, 2]", b"\xff"):
        assert discovered_dependencies.parse(bad) is None, bad


def _declared(name="pkg:part", data="declared"):
    key = CacheHash(name, cache=True)
    key.add_string(data)
    return key


def test_a_part_is_keyed_on_the_name_and_content_of_each_file_and_on_nothing_more_where_there_are_none(tmp_path):
    layer = tmp_path / "geom.usda"
    layer.write_text("one")
    declared = _declared()
    assert discovered_dependencies.keyed_on(declared, [], str(tmp_path)) is declared
    first = discovered_dependencies.keyed_on(declared, ["geom.usda"], str(tmp_path)).get()
    assert first != declared.get()
    assert discovered_dependencies.keyed_on(_declared(), ["geom.usda"], str(tmp_path)).get() == first
    # Wherever the package is: the same name and the same content are the same key.
    elsewhere = tmp_path / "copy"
    elsewhere.mkdir()
    (elsewhere / "geom.usda").write_text("one")
    assert discovered_dependencies.keyed_on(_declared(), ["geom.usda"], str(elsewhere)).get() == first
    layer.write_text("two")
    assert discovered_dependencies.keyed_on(_declared(), ["geom.usda"], str(tmp_path)).get() != first
    # A file that is not there is keyed as missing, so its appearing builds the part again.
    missing = discovered_dependencies.keyed_on(_declared(), ["gone.png"], str(tmp_path)).get()
    assert missing not in (first, declared.get())
    # And a part that is not cached has no key to continue.
    assert discovered_dependencies.keyed_on(CacheHash("pkg:part"), ["geom.usda"], str(tmp_path)).get() is None


def test_a_snapshot_is_the_hash_as_it_would_finish_and_leaves_it_open(tmp_path):
    declared_file = tmp_path / "part.box"
    declared_file.write_text("box")
    key = _declared()
    key.set_dependencies([str(declared_file)])
    snapshot = key.snapshot()
    assert not key.is_used
    expected = snapshot.get()
    key.add_string("more")  # still open: no warning, and it goes on to differ
    assert key.get() != expected
    assert _declared_with(declared_file).get() == expected
    assert CacheHash("pkg:part").snapshot().get() is None


def _declared_with(path):
    key = _declared()
    key.set_dependencies([str(path)])
    return key


# ---------------------------------------------------------------------------
# A part type that reports what it read, through the wrapper and the cache
# ---------------------------------------------------------------------------


READER = """
import os

from build123d import Box

if __name__ == "__partcad_part__":
    # A '.box' file names the file its size is in, as a stage names its layers.
    with open(request["path"]) as f:
        sizes = f.readline().strip()
    with open(os.path.join(os.path.dirname(request["path"]), sizes)) as f:
        size = float(f.read())
    output = {"shape": Box(size, size, size).wrapped, "dependencies": [sizes, "never-read.txt", 3]}
"""


def _package(root, reports, script=READER):
    root.mkdir(parents=True, exist_ok=True)
    part_type = {"kind": "wrapper", "path": "reader.py", "extension": "box"}
    if reports is not None:
        part_type["reportsDependencies"] = reports
    config = {"name": "//src", "partTypes": {"boxed": part_type}, "parts": {"crate": {"type": ":boxed"}}}
    (root / "partcad.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    (root / "reader.py").write_text(script)
    # A line nothing reads, which makes this package's part one no other test,
    # and no earlier run of this one, has put in the shared cache.
    (root / "crate.box").write_text("sizes.txt\n%s\n" % uuid.uuid4())
    (root / "sizes.txt").write_text("10")
    return root


def _built(root):
    """A fresh context's crate: (its size, its key, whether it was read back rather than built)."""
    import ocp_serialize
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    ctx = pc.Context(str(root))
    part = ctx.get_part("//src:crate")
    cached = asyncio.run(part.is_cached_async(ctx))
    envelope = asyncio.run(part.get_wrapped(ctx))
    assert envelope is not None, part.errors
    box = Bnd_Box()
    BRepBndLib.Add_s(ocp_serialize.decode_shape(envelope), box, False)
    xmin, _, _, xmax, _, _ = box.Get()
    return round(xmax - xmin, 3), asyncio.run(part.get_cache_key_async()), cached


def test_a_part_type_that_reports_what_it_read_is_built_again_when_that_changes(tmp_path):
    pytest.importorskip("build123d")
    root = _package(tmp_path / "pkg", reports=True)
    size, first, cached = _built(root)
    assert (size, cached) == (10.0, False)
    # Read back now, under the key the build gave it.
    assert _built(root) == (10.0, first, True)
    (root / "sizes.txt").write_text("20")
    size, second, cached = _built(root)
    assert (size, cached) == (20.0, False) and second != first
    assert _built(root) == (20.0, second, True)


def test_a_part_type_that_does_not_is_read_back_from_before(tmp_path):
    pytest.importorskip("build123d")
    root = _package(tmp_path / "pkg", reports=None)
    size, first, _ = _built(root)
    (root / "sizes.txt").write_text("20")
    assert _built(root) == (size, first, True)


def test_a_part_type_that_says_something_else_is_not_cached(tmp_path):
    root = _package(tmp_path / "pkg", reports="sometimes")
    part = pc.Context(str(root)).get_part("//src:crate")
    assert asyncio.run(part.get_cache_key_async()) is None


def test_the_wrapper_hands_back_what_the_script_said_it_read_and_nothing_that_is_not_a_path(tmp_path, monkeypatch):
    pytest.importorskip("build123d")
    import wrapper_common

    root = _package(tmp_path / "pkg", reports=True)
    written = []
    request = {"path": str(root / "crate.box")}
    monkeypatch.setattr(wrapper_common, "handle_input", lambda *_args, **_kwargs: (str(root / "reader.py"), request))
    monkeypatch.setattr(wrapper_common, "handle_output", written.append)
    sys.modules.pop("wrapper_part_type", None)
    try:
        importlib.import_module("wrapper_part_type")
    finally:
        sys.modules.pop("wrapper_part_type", None)
    (said,) = written
    assert said["success"], said["exception"]
    assert said["dependencies"] == ["sizes.txt", "never-read.txt"]


def test_a_part_type_that_starts_reporting_is_built_again_rather_than_served_from_before_it_did(tmp_path):
    pytest.importorskip("build123d")
    root = _package(tmp_path / "pkg", reports=None)
    _, before, _ = _built(root)
    config = yaml.safe_load((root / "partcad.yaml").read_text())
    config["partTypes"]["boxed"]["reportsDependencies"] = True
    (root / "partcad.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    size, after, cached = _built(root)
    assert (size, cached) == (10.0, False) and after != before
    # And from then on, what it read is what it is kept for.
    (root / "sizes.txt").write_text("30")
    assert _built(root)[0] == 30.0


def test_a_part_whose_script_cannot_tell_what_it_read_is_not_cached(tmp_path):
    """Kept under a key that leaves those files out, it would be served after one of them changed."""
    pytest.importorskip("build123d")
    unknown = READER.replace('"dependencies": [sizes, "never-read.txt", 3]', '"dependencies": None')
    assert unknown != READER
    root = _package(tmp_path / "pkg", reports=True, script=unknown)
    assert _built(root)[2] is False
    assert _built(root)[2] is False
    (root / "sizes.txt").write_text("20")
    assert _built(root)[0] == 20.0


def test_the_wrapper_says_when_the_script_could_not_tell_what_it_read(tmp_path, monkeypatch):
    pytest.importorskip("build123d")
    import wrapper_common

    unknown = READER.replace('"dependencies": [sizes, "never-read.txt", 3]', '"dependencies": None')
    root = _package(tmp_path / "pkg", reports=True, script=unknown)
    written = []
    request = {"path": str(root / "crate.box")}
    monkeypatch.setattr(wrapper_common, "handle_input", lambda *_args, **_kwargs: (str(root / "reader.py"), request))
    monkeypatch.setattr(wrapper_common, "handle_output", written.append)
    sys.modules.pop("wrapper_part_type", None)
    try:
        importlib.import_module("wrapper_part_type")
    finally:
        sys.modules.pop("wrapper_part_type", None)
    (said,) = written
    assert said["success"] and "dependencies" in said and said["dependencies"] is None
