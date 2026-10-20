#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A partType that reads a file, declared in one package and used from another.

That is what a plugin package teaching PartCAD a format is, so it is checked
without one: 'reader' declares a partType for '.box' files and 'consumer'
imports it. The file belongs to the package declaring the part; the image the
part is keyed under and the cache directory the script is handed belong to the
package declaring the type.
"""

import asyncio
import functools
import http.server
import os
import random
import shutil
import threading

import pytest

import partcad as pc
from partcad import output, shape_envelope

DATA = os.path.join("tests", "partcad", "unit", "data", "part_type_file")
CONSUMER = os.path.join(DATA, "consumer")
READER = os.path.join(DATA, "reader")


@pytest.fixture(scope="module")
def ctx():
    return pc.Context(os.path.join(CONSUMER, "partcad.yaml"))


def test_the_file_is_the_consumer_s(ctx):
    crate = ctx.get_part(":crate")
    assert os.path.abspath(crate.path) == os.path.abspath(os.path.join(CONSUMER, "crate.box"))
    assert os.path.abspath(crate.path) in [os.path.abspath(p) for p in crate.cache_dependencies]
    elsewhere = ctx.get_part(":crate_elsewhere")
    assert os.path.abspath(elsewhere.path) == os.path.abspath(os.path.join(CONSUMER, "files", "other.box"))


def test_the_image_and_the_cache_are_the_reader_s(ctx):
    assert ctx.get_part(":crate").environment_cache_key.endswith(";image=ghcr.io/partcad/partcad-test-box-reader:1")
    reader = ctx.get_project("//reader")
    assert output.package_cache_dir(ctx, reader) == os.path.join(os.path.abspath(READER), ".cache")


def test_the_builtin_packages_keep_theirs_in_the_state_directory(ctx):
    builtin = ctx.get_project("//builtin/import")
    assert output.package_cache_dir(ctx, builtin) == os.path.join(
        ctx.user_config.internal_state_dir, "builtin", "import"
    )


@pytest.mark.slow
def test_the_reader_reads_the_consumer_s_file(tmp_path):
    # A copy, so that what the script leaves in its cache stays out of the tree,
    # and a box of a size nobody has asked for before: the part is keyed on its
    # file's content, and one already in the shape cache would never run the
    # script at all.
    shutil.copytree(DATA, tmp_path / "data")
    depth = 1 + random.random()
    (tmp_path / "data" / "consumer" / "crate.box").write_text("10 20 %r\n" % depth)
    ctx = pc.Context(str(tmp_path / "data" / "consumer" / "partcad.yaml"))
    part = ctx.get_part(":crate")
    envelope = asyncio.run(part.get_wrapped(ctx))
    assert envelope is not None, part.errors
    measured = envelope[shape_envelope.KEY_METADATA][shape_envelope.METADATA_MEASUREMENTS]
    assert measured["volume"] == pytest.approx(10 * 20 * depth)
    with open(tmp_path / "data" / "reader" / ".cache" / "read", encoding="utf-8") as f:
        assert f.read() == str(tmp_path / "data" / "consumer" / "crate.box")


def _consumer_with(tmp_path, part):
    """A copy of the consumer package declaring 'part' as well."""
    shutil.copytree(DATA, tmp_path / "data")
    with open(tmp_path / "data" / "consumer" / "partcad.yaml", "a", encoding="utf-8") as f:
        f.write(part)
    return pc.Context(str(tmp_path / "data" / "consumer" / "partcad.yaml"))


def test_a_missing_file_is_reported_before_the_script_runs(tmp_path):
    ctx = _consumer_with(tmp_path, "  lost:\n    type: reader:box_file\n")
    part = ctx.get_part(":lost")
    assert asyncio.run(part.get_wrapped(ctx)) is None
    assert any("file is not found" in str(error) for error in part.errors)


def test_a_file_that_cannot_be_fetched_fails_the_part(tmp_path):
    # As it does a STEP part's: the download is part of preparing the part.
    # Served from an empty directory, so the file is a 404.
    empty = tmp_path / "empty"
    empty.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(empty))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = "http://127.0.0.1:%d/fetched.box" % server.server_address[1]
        ctx = _consumer_with(
            tmp_path, "  fetched:\n    type: reader:box_file\n    fileFrom: url\n    fileUrl: %s\n" % url
        )
        with pytest.raises(Exception, match="404"):
            asyncio.run(ctx.get_part(":fetched").get_wrapped(ctx))
    finally:
        server.shutdown()
        server.server_close()
