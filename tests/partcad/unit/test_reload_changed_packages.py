#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A context kept warm reloads the packages whose 'partcad.yaml' changed, and only those.

The daemon keeps a context for as long as it runs, and a context reads each
package's configuration once. So an edited 'partcad.yaml' went unseen until the
daemon was stopped. Reloading the whole context would see it, and throw away
every other package and every sandbox with it; reloading the package, and the
packages underneath it, sees it and keeps the rest.
"""

import asyncio
import os

import pytest

import partcad as pc


def _declare(path, parts):
    lines = ["parts:"]
    for name in parts:
        lines += ["  %s:" % name, "    type: step", "    path: %s.step" % name]
        (path / ("%s.step" % name)).write_text(name)
    (path / "partcad.yaml").write_text("\n".join(lines) + "\n")


@pytest.fixture
def workspace(tmp_path):
    """A root, a package under it, one under that, and a sibling."""
    _declare(tmp_path, ["top"])
    for sub, parts in (("left", ["a"]), (os.path.join("left", "deep"), ["d"]), ("right", ["r"])):
        (tmp_path / sub).mkdir()
        _declare(tmp_path / sub, parts)
    return tmp_path


def _part(ctx, spec):
    return asyncio.run(ctx._get_part_async(spec))


def _touch(path, text="\n# edited\n"):
    with open(path, "a") as f:
        f.write(text)


@pytest.fixture
def ctx(workspace):
    ctx = pc.Context(str(workspace))
    for spec in ("//:top", "//left:a", "//left/deep:d", "//right:r"):
        assert _part(ctx, spec) is not None, spec
    return ctx


def test_nothing_is_reloaded_when_nothing_changed(ctx):
    assert ctx.reload_changed_packages() == []


def test_a_changed_package_is_reloaded_with_its_children_and_nothing_else(ctx, workspace):
    top, a, d, r = (_part(ctx, s) for s in ("//:top", "//left:a", "//left/deep:d", "//right:r"))

    _touch(workspace / "left" / "partcad.yaml")

    assert sorted(ctx.reload_changed_packages()) == ["//left", "//left/deep"]
    # Reloaded: new objects, read from disk again.
    assert _part(ctx, "//left:a") is not a
    assert _part(ctx, "//left/deep:d") is not d
    # Not reloaded: the very same objects, with whatever they had built.
    assert _part(ctx, "//:top") is top
    assert _part(ctx, "//right:r") is r
    # And once is enough.
    assert ctx.reload_changed_packages() == []


def test_a_reloaded_package_declares_what_its_file_now_says(ctx, workspace):
    _declare(workspace / "left", ["a", "b"])

    ctx.reload_changed_packages()

    assert _part(ctx, "//left:b") is not None


def test_a_changed_root_reloads_every_package_in_the_same_context(ctx, workspace):
    r = _part(ctx, "//right:r")

    _declare(workspace, ["top", "added"])

    dropped = ctx.reload_changed_packages()
    assert {"//", "//left", "//left/deep", "//right"} <= set(dropped)
    assert _part(ctx, "//:added") is not None
    assert _part(ctx, "//right:r") is not r


def test_a_part_file_edit_does_not_reload_anything(ctx, workspace):
    """Only a package's configuration is watched, not the files its objects read."""
    _touch(workspace / "left" / "a.step")

    assert ctx.reload_changed_packages() == []
