#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc add' given a URL pins what it fetched.

An object added from a URL is not reproducible unless the declaration says which
bytes to expect, and asking the author to go and compute a digest by hand would
be asking them to do what the machine has just done: adding the object fetches
the file once, so the hash is there for the taking. It is written in, and the
author is left with an object that is pinned from the moment it exists.
"""

import asyncio
import hashlib
import os

import pytest
import yaml

import partcad as pc
from http_server import serve
from partcad.actions.add import (
    add_object_from_url_async,
    filename_from_url,
    looks_like_url,
    object_name_from_filename,
)
from partcad.file_factory import unreproducible_reason

BOLT = b"ISO-10303-21;\nthis is not really a STEP file\nEND-ISO-10303-21;\n"
BOLT_SHA256 = "sha256:" + hashlib.sha256(BOLT).hexdigest()


@pytest.fixture
def package(tmp_path):
    """An empty package to add things to."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "partcad.yaml").write_text("desc: A package under test\n")
    return pkg


@pytest.fixture
def served(tmp_path):
    """A directory served over HTTP, holding 'bolt.step'."""
    directory = tmp_path / "served"
    directory.mkdir()
    (directory / "bolt.step").write_bytes(BOLT)
    return directory


def _declared(pkg, section, name):
    return yaml.safe_load((pkg / "partcad.yaml").read_text())[section][name]


#
# Telling a URL from a path
#


@pytest.mark.parametrize(
    "value, is_url",
    [
        ("https://example.com/vendor/bolt.step", True),
        ("http://example.com/vendor/bolt.step", True),
        ("bolt.step", False),
        ("/home/user/bolt.step", False),
        ("./bolt.step", False),
        # A Windows path has a drive letter, not a scheme PartCAD can fetch.
        ("C:\\models\\bolt.step", False),
        # Nor is every scheme one 'fileFrom' knows.
        ("ftp://example.com/bolt.step", False),
        ("git@github.com:owner/repo.git", False),
        # A scheme with no authority behind it: 'urlparse' reads this as the
        # scheme 'https', but it is a file name a shell hands over verbatim,
        # and there is no host to fetch it from.
        ("https:firmware.bin", False),
        ("https://", False),
        (None, False),
    ],
)
def test_a_url_is_told_from_a_path(value, is_url):
    assert looks_like_url(value) is is_url


@pytest.mark.parametrize(
    "url, filename",
    [
        ("https://example.com/vendor/bolt.step", "bolt.step"),
        # Percent-encoding is undone, so the name is what a browser would save.
        ("https://example.com/vendor/bolt%20v2.step", "bolt v2.step"),
        ("https://example.com/vendor/bolt.step?rev=4", "bolt.step"),
        # Nothing that could climb out of the package, and nothing empty.
        ("https://example.com/", "fallback"),
        ("https://example.com/vendor/..", "fallback"),
    ],
)
def test_the_file_name_comes_from_the_url(url, filename):
    assert filename_from_url(url, fallback="fallback") == filename


@pytest.mark.parametrize(
    "filename, extension, name",
    [
        ("bolt.step", "step", "bolt"),
        # Only the kind's own extension is stripped, so the name still points at
        # the file it came from.
        ("bolt.v2.step", "step", "bolt.v2"),
        ("readme.md", "step", "readme.md"),
        # Software has no extension PartCAD can predict, so any is stripped.
        ("install.sh", None, "install"),
        ("firmware", None, "firmware"),
    ],
)
def test_the_object_name_comes_from_the_file_name(filename, extension, name):
    assert object_name_from_filename(filename, extension) == name


#
# Adding from a URL
#


def test_a_part_added_from_a_url_is_pinned(package, served):
    with serve(served) as url:
        ctx = pc.Context(str(package))
        project = ctx.get_project("//")
        name = asyncio.run(
            add_object_from_url_async(
                ctx, project, "parts", "%s/bolt.step" % url, kind="step", config={"desc": "A bolt"}
            )
        )

    assert name == "bolt"
    declared = _declared(package, "parts", "bolt")
    assert declared["type"] == "step"
    assert declared["desc"] == "A bolt"
    assert declared["path"] == "bolt.step"
    assert declared["fileFrom"] == "url"
    assert declared["fileUrl"].endswith("/bolt.step")
    assert declared["fileHash"] == BOLT_SHA256


def test_what_was_added_from_a_url_is_reproducible(package, served):
    """The point of fetching it: the declaration is pinned from the start."""
    with serve(served) as url:
        ctx = pc.Context(str(package))
        asyncio.run(add_object_from_url_async(ctx, ctx.get_project("//"), "parts", "%s/bolt.step" % url, kind="step"))

    assert unreproducible_reason(_declared(package, "parts", "bolt")) is None


def test_the_fetched_copy_is_not_left_behind(package, served):
    """The package deliberately does not carry the file; 'pc install' fetches it."""
    with serve(served) as url:
        ctx = pc.Context(str(package))
        asyncio.run(add_object_from_url_async(ctx, ctx.get_project("//"), "parts", "%s/bolt.step" % url, kind="step"))

    assert sorted(os.listdir(package)) == ["partcad.yaml"]


def test_software_added_from_a_url_has_no_type(package, served):
    """'raw' is the only software type there is, so nothing is written for it."""
    with serve(served) as url:
        ctx = pc.Context(str(package))
        name = asyncio.run(add_object_from_url_async(ctx, ctx.get_project("//"), "software", "%s/bolt.step" % url))

    assert name == "bolt"
    declared = _declared(package, "software", "bolt")
    assert "type" not in declared
    assert declared["path"] == "bolt.step"
    assert declared["fileHash"] == BOLT_SHA256


def test_a_fetch_that_fails_writes_nothing(package, served):
    """No bytes, no hash - and a declaration written anyway would be unpinned."""
    with serve(served) as url:
        ctx = pc.Context(str(package))
        with pytest.raises(Exception):
            asyncio.run(
                add_object_from_url_async(ctx, ctx.get_project("//"), "parts", "%s/nowhere.step" % url, kind="step")
            )

    assert yaml.safe_load((package / "partcad.yaml").read_text()) == {"desc": "A package under test"}


def test_the_declaration_is_written_on_one_line(package, served):
    """A URL folded across two lines is unreadable and easy to break by hand."""
    with serve(served) as url:
        ctx = pc.Context(str(package))
        asyncio.run(add_object_from_url_async(ctx, ctx.get_project("//"), "parts", "%s/bolt.step" % url, kind="step"))

    for line in (package / "partcad.yaml").read_text().splitlines():
        if "fileUrl" in line or "fileHash" in line:
            assert line.strip().endswith(("step", BOLT_SHA256.split(":")[1]))


#
# Adding software the package already has
#


def test_software_is_added_from_a_local_file(package):
    (package / "firmware.bin").write_bytes(b"image\n")
    project = pc.Context(str(package)).get_project("//")

    assert project.add_software(str(package / "firmware.bin"), {"desc": "The image"})

    declared = _declared(package, "software", "firmware")
    assert declared == {"desc": "The image", "path": "firmware.bin"}
    # It is in the package, so it needs no hash to be reproducible.
    assert unreproducible_reason(declared) is None


def test_a_directory_is_not_software(package):
    """Software is always a file, and the refusal belongs to the command.

    A directory is inside the package like any file, so the path check passes
    it. Written down, it would be refused by 'SoftwareFactoryFile' on the next
    load instead -- far from the command that wrote it.
    """
    (package / "images").mkdir()
    project = pc.Context(str(package)).get_project("//")

    assert not project.add_software(str(package / "images"))
    assert yaml.safe_load((package / "partcad.yaml").read_text()) == {"desc": "A package under test"}


def test_software_outside_the_package_is_refused(package, tmp_path):
    outside = tmp_path / "elsewhere.bin"
    outside.write_bytes(b"image\n")
    project = pc.Context(str(package)).get_project("//")

    assert not project.add_software(str(outside))
    assert yaml.safe_load((package / "partcad.yaml").read_text()) == {"desc": "A package under test"}
