#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Manufacturing is repetition, so what is made has to be identified.

An object read from a file the package fetches rather than carries cannot
promise that the next run produces the same thing -- the URL is free to serve
something else tomorrow -- unless it says which bytes it expects. 'fileHash'
next to 'fileUrl' is that statement. It stays optional in the declaration, and
the manufacturing test is the one place it is insisted on.

A file a repository plugin serves is exempt for now: a 'fileHash' given for one
is verified like any other, it is simply not required yet.
"""

import asyncio
import hashlib

import pytest

import partcad as pc
from partcad.file_factory import FileHashError, declared_hash, is_package_file, unreproducible_reason
from partcad.file_factory_plugin import FileFactoryPlugin
from partcad.test import cam
from partcad.test.test import Test

DATA = "tests/partcad/unit/data/cam_reproducibility"

PROVIDER_NAME = "//:store"

# What the fake plugin below serves, and the hash that pins it.
SERVED = b"served bytes\n"
SERVED_SHA256 = "sha256:" + hashlib.sha256(SERVED).hexdigest()


class _Provider:
    """A provider that answers without a sandbox, unlike a real one."""

    def __init__(self) -> None:
        self.name = PROVIDER_NAME

    async def is_part_available(self, cart_item) -> bool:
        return True


@pytest.fixture
def ctx():
    """A context whose supplier lookup is answered locally.

    The manufacturing test ends with a supplier query, and this is not the test
    for that: without this every part below would fail for the wrong reason.
    """
    ctx = pc.Context(DATA)

    async def find_part_suppliers(cart_item, cart=None):
        return [PROVIDER_NAME]

    ctx.find_part_suppliers = find_part_suppliers
    ctx.get_provider = lambda name, params=None: _Provider()
    return ctx


def _run(ctx, name, kind="part"):
    getters = {
        "part": ctx.get_part,
        "assembly": ctx._get_assembly,
        "sketch": ctx.get_sketch,
    }
    shape = getters[kind]("//:%s" % name)
    assert shape is not None
    test = cam.CamTest()
    return test, shape, asyncio.run(test.test([test], ctx, shape))


#
# The rule
#


def test_a_carried_file_is_reproducible(ctx):
    """The package's revision identifies it; there is nothing left to say."""
    test, part, result = _run(ctx, "carried")
    assert test.reproducibility_failure(part) is None
    assert result == Test.TEST_PASSED


def test_a_pinned_download_is_reproducible(ctx):
    """Fetched, but the bytes are stated in advance."""
    test, part, result = _run(ctx, "fetched-pinned")
    assert test.reproducibility_failure(part) is None
    assert result == Test.TEST_PASSED


def test_an_unpinned_download_is_not_manufacturable(ctx):
    """The whole point: available is not the same as identified."""
    test, part, result = _run(ctx, "fetched-unpinned")
    assert result == Test.TEST_FAILED

    failure = test.reproducibility_failure(part)
    assert failure is not None
    assert "not reproducible" in failure
    assert "fileHash" in failure
    # Nothing was fetched to find this out: the declaration is enough.
    assert not part.config.get("fileHash")


def test_an_unpinned_assembly_is_not_manufacturable(ctx):
    """An ASSY file pulled from a URL is no more repeatable than a part is."""
    test, assembly, result = _run(ctx, "fetched-unpinned-assembly", "assembly")
    assert result == Test.TEST_FAILED
    assert "not reproducible" in test.reproducibility_failure(assembly)


#
# What a part may say instead
#


def test_a_part_that_is_bought_is_reproducible_without_a_hash(ctx):
    """A vendor and an SKU are their own answer to "the same again"."""
    test, part, result = _run(ctx, "fetched-purchasable")
    assert test.reproducibility_failure(part) is None
    assert result == Test.TEST_PASSED


def test_half_a_purchase_is_not_a_purchase(ctx):
    """A vendor without an SKU does not say what to order."""
    test, part, result = _run(ctx, "fetched-vendor-only")
    assert result == Test.TEST_FAILED
    failure = test.reproducibility_failure(part)
    assert failure is not None and "vendor and SKU" in failure


#
# What a sketch may not
#


def test_a_carried_sketch_is_reproducible(ctx):
    test, sketch, result = _run(ctx, "outline", "sketch")
    assert test.reproducibility_failure(sketch) is None
    assert result == Test.TEST_PASSED


def test_an_unpinned_sketch_is_not_reproducible(ctx):
    """A sketch cannot be bought, so for it the file is the whole question.

    Nothing manufactures a drawing, but a part extruded from one is no more
    repeatable than the drawing was, and this is where that is worth saying.
    """
    test, sketch, result = _run(ctx, "fetched-outline", "sketch")
    assert result == Test.TEST_FAILED
    assert "not reproducible" in test.reproducibility_failure(sketch)


def test_a_sketch_is_asked_nothing_else(ctx):
    """The rest of the manufacturing test does not apply to a drawing."""
    test, sketch, result = _run(ctx, "outline", "sketch")
    # No vendor, no SKU, no manufacturing method, no tolerance - and it passes.
    assert sketch.get_store_data().is_purchasable is False
    assert result == Test.TEST_PASSED


def test_a_part_that_is_not_manufacturable_is_not_asked(ctx):
    """Nothing is required of what nobody said would be made."""
    part = ctx.get_part("//:fetched-unpinned")
    part.is_manufacturable = False
    test = cam.CamTest()
    assert asyncio.run(test.test([test], ctx, part)) == Test.TEST_PASSED


#
# The declaration stays optional
#


def test_the_declaration_is_optional(ctx):
    """'fileHash' is not required to load, to build, or to lint a part.

    Only to call it manufacturable. A package that pulls a vendor's model from a
    URL and never claims it can be made is untouched by any of this.
    """
    part = ctx.get_part("//:fetched-unpinned")
    assert part is not None
    assert ctx.get_project("//").get_broken_object_reason("part", "fetched-unpinned") is None


#
# What a repository plugin serves
#


def test_a_plugin_file_is_not_required_to_be_pinned_yet(ctx):
    """Exempt for now, deliberately, and the same either way if one is given."""
    assert is_package_file({"fileFrom": "plugin"})
    assert unreproducible_reason({"fileFrom": "plugin"}) is None
    assert unreproducible_reason({"fileFrom": "plugin", "fileHash": SERVED_SHA256}) is None
    # Which is not true of anything else that is fetched.
    assert unreproducible_reason({"fileFrom": "url"}) is not None


class _PluginProject:
    """A package that serves its own files, as an external repository does."""

    def __init__(self, content):
        self.content = content

    async def get_data_async(self, key):
        assert key == "files/board.py"
        return self.content


def _plugin_factory(project, file_hash=None):
    config = {"name": "board", "orig_name": "board", "path": "board.py"}
    if file_hash is not None:
        config["fileHash"] = file_hash
    return FileFactoryPlugin(None, project, project, config)


def test_a_plugin_file_is_verified_when_it_is_pinned(tmp_path):
    """Given a 'fileHash', a plugin's file is checked like any other."""
    factory = _plugin_factory(_PluginProject(SERVED), file_hash=SERVED_SHA256)
    assert declared_hash(factory.config) == SERVED_SHA256

    path = str(tmp_path / "board.py")
    asyncio.run(factory.download(path))
    assert open(path, "rb").read() == SERVED


def test_a_plugin_file_that_does_not_match_is_refused(tmp_path):
    factory = _plugin_factory(_PluginProject(SERVED), file_hash="sha256:" + "0" * 64)

    path = str(tmp_path / "board.py")
    with pytest.raises(FileHashError):
        asyncio.run(factory.download(path))
    assert not (tmp_path / "board.py").exists()


def test_a_plugin_file_without_a_hash_is_served_unchecked(tmp_path):
    factory = _plugin_factory(_PluginProject(SERVED))

    path = str(tmp_path / "board.py")
    asyncio.run(factory.download(path))
    assert open(path, "rb").read() == SERVED


#
# The cached answer has to follow the declaration
#


def test_the_cache_key_follows_the_declared_file_hash(ctx):
    """Adding the 'fileHash' that was missing must re-run the test.

    A shape's cache key covers what it is built from, and the text of the
    declaration is not that: without this, pinning the download would be
    answered with the cached failure of the declaration that had not.
    """
    test = cam.CamTest()
    carried = ctx.get_part("//:carried")
    unpinned = ctx.get_part("//:fetched-unpinned")

    # An object that fetches nothing and ships nothing keys as it always did.
    assert test.cache_key_suffix(ctx, carried) == ""

    before = test.cache_key_suffix(ctx, unpinned)
    assert before != ""
    unpinned.config["fileHash"] = "sha256:" + "0" * 64
    assert test.cache_key_suffix(ctx, unpinned) != before
