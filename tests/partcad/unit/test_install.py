#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What 'pc install' has to do to leave a package ready to build.

The whole point of the command is the state it leaves behind: every file a
'fileFrom' points at is on disk, every package an object really depends on is
loaded, and the cache key an object reports afterwards is the same one its first
build will look up - so that build is a cache hit and not a miss.

Nothing here reaches the network: the URL file factory is replaced by a recorder
that writes a known body, which is also what makes the file's content - and so
the cache key that hashes it - predictable.
"""

import asyncio
import os

import pytest

import partcad as pc
from partcad.file_factory_url import FileFactoryUrl


@pytest.fixture
def downloads(monkeypatch):
    """Stand in for the network; returns the list of URLs that were fetched."""
    fetched = []

    async def fake_download(self, path):
        fetched.append(self.url)
        dirs = os.path.dirname(path)
        if dirs and not os.path.exists(dirs):
            os.makedirs(dirs)
        with open(path, "w") as f:
            f.write("solid downloaded from %s\nendsolid\n" % self.url)

    monkeypatch.setattr(FileFactoryUrl, "download", fake_download)
    return fetched


def write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def install(ctx):
    """Install the package the context was created for."""
    return pc.actions.package.install(ctx, [ctx.get_current_project_path()])


REMOTE_PART = """
parts:
  bolt:
    type: stl
    fileFrom: url
    fileUrl: https://example.com/bolt.stl
"""


def test_install_downloads_the_files_behind_file_from(tmp_path, downloads):
    write(tmp_path / "partcad.yaml", REMOTE_PART)
    ctx = pc.Context(str(tmp_path))
    assert not (tmp_path / "bolt.stl").exists()

    stats = install(ctx)

    assert stats == {"sketch": 0, "part": 1, "assembly": 0, "software": 0, "failed": 0, "failed_packages": 0}
    assert downloads == ["https://example.com/bolt.stl"]
    assert (tmp_path / "bolt.stl").exists()


def test_the_installed_cache_key_is_the_one_the_build_will_look_up(tmp_path, downloads):
    """The key hashes the file's content, so it is wrong until the file is there.

    Without the download the part hashes a file that does not exist, which is a
    different key from the one the build computes once it has fetched the file -
    a guaranteed miss on the cache the install just paid for.
    """
    write(tmp_path / "partcad.yaml", REMOTE_PART)

    unprepared = pc.Context(str(tmp_path))._get_part(":bolt").hash.get()
    assert downloads == []

    # A fresh context each time: a hash is computed once per shape and kept.
    installed = asyncio.run(pc.Context(str(tmp_path))._get_part(":bolt").get_cache_key_async())
    later_build = pc.Context(str(tmp_path))._get_part(":bolt").hash.get()

    assert installed is not None
    assert installed == later_build
    assert installed != unprepared


def dependency_on_sub(body: str) -> str:
    return """
dependencies:
  sub:
    type: local
    path: sub
""" + body


def test_install_reaches_the_package_an_alias_points_at(tmp_path, downloads):
    """An alias names the package it really depends on; installing follows it."""
    write(tmp_path / "sub" / "partcad.yaml", REMOTE_PART)
    write(
        tmp_path / "partcad.yaml",
        dependency_on_sub("""
parts:
  bolt:
    type: alias
    package: sub
    source: bolt
"""),
    )
    ctx = pc.Context(str(tmp_path))

    stats = install(ctx)

    assert stats["part"] == 1 and stats["failed"] == 0
    assert (tmp_path / "sub" / "bolt.stl").exists()


def test_install_reaches_the_package_an_enrich_points_at(tmp_path, downloads):
    write(tmp_path / "sub" / "partcad.yaml", REMOTE_PART)
    write(
        tmp_path / "partcad.yaml",
        dependency_on_sub("""
parts:
  bolt:
    type: enrich
    package: sub
    source: bolt
    desc: The very same bolt
"""),
    )
    ctx = pc.Context(str(tmp_path))

    stats = install(ctx)

    assert stats["part"] == 1 and stats["failed"] == 0
    assert (tmp_path / "sub" / "bolt.stl").exists()


def test_install_walks_the_links_of_an_assembly(tmp_path, downloads):
    """An ASSY link can name a package nothing else in the tree references."""
    write(tmp_path / "sub" / "partcad.yaml", REMOTE_PART)
    write(
        tmp_path / "partcad.yaml",
        dependency_on_sub("""
assemblies:
  top:
    type: assy
"""),
    )
    write(
        tmp_path / "top.assy",
        """
links:
  - part: bolt
    package: sub
""",
    )
    ctx = pc.Context(str(tmp_path))

    stats = install(ctx)

    assert stats == {"sketch": 0, "part": 0, "assembly": 1, "software": 0, "failed": 0, "failed_packages": 0}
    assert (tmp_path / "sub" / "bolt.stl").exists()


def test_assemblies_that_link_to_each_other_do_not_recurse_forever(tmp_path, downloads):
    write(
        tmp_path / "partcad.yaml",
        """
assemblies:
  first:
    type: assy
  second:
    type: assy
""",
    )
    write(tmp_path / "first.assy", "links:\n  - assembly: second\n")
    write(tmp_path / "second.assy", "links:\n  - assembly: first\n")
    ctx = pc.Context(str(tmp_path))

    stats = install(ctx)

    assert stats["assembly"] == 2
    assert stats["failed"] == 0


def test_a_package_that_cannot_be_read_is_counted_separately(tmp_path, downloads):
    """A package whose objects cannot even be enumerated is not an object failure."""
    write(tmp_path / "partcad.yaml", REMOTE_PART)
    ctx = pc.Context(str(tmp_path))

    stats = pc.actions.package.install(ctx, ["//nowhere"])

    assert stats["failed_packages"] == 1
    assert stats["failed"] == 0


def test_an_object_that_cannot_be_prepared_is_counted_not_raised(tmp_path, downloads):
    """One broken object must not cost the user everything else in the package."""
    write(
        tmp_path / "partcad.yaml",
        REMOTE_PART + """  missing:
    type: alias
    source: nowhere
""",
    )
    ctx = pc.Context(str(tmp_path))

    stats = install(ctx)

    assert stats["part"] == 1  # the good one was still installed
    assert stats["failed"] == 1
    assert (tmp_path / "bolt.stl").exists()
