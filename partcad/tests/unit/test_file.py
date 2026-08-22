#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-04-17
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import contextlib
import functools
import http.server
import os
import threading

import pytest

import partcad as pc


def test_file_url_part_1():
    """Download a STEP file from a URL"""
    # TODO(clairbee): make this test work with no parameter passed into "Context": the root package may be broken or the absent config is not a broken package?
    ctx = pc.Context("examples")
    pkg = ctx.get_project(".")
    assert pkg is not None

    config = {
        "name": "boltFromUrl",
        "orig_name": "boltFromUrl",
        "type": "step",
        "path": "bolt.step",
        "fileFrom": "url",
        "fileUrl": "https://raw.githubusercontent.com/openvmp/partcad/devel/examples/produce_part_step/bolt.step",
    }
    pkg.init_part_by_config(config)
    # See if it worked
    assert "boltFromUrl" in pkg.parts
    assert pkg.parts["boltFromUrl"] is not None
    bolt = pkg.get_part("boltFromUrl")

    assert bolt is not None
    assert os.path.exists(bolt.path) is False

    bolt.cacheable = False
    wrapped = asyncio.run(bolt.get_wrapped(ctx))
    assert wrapped is not None

    assert os.path.exists(bolt.path) is True
    os.unlink(bolt.path)


@contextlib.contextmanager
def _serve(directory):
    """Serve 'directory' over HTTP on a private loopback port.

    Downloads go through 'aiohttp', so a file:// URL is not an option: the test
    needs something that actually speaks HTTP. Binding to port 0 keeps the
    server private to this test, so tests can still run in parallel.
    """
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_file_url_assembly_1(tmp_path):
    """Download an ASSY file from a URL"""
    served = tmp_path / "served"
    served.mkdir()
    (served / "downloaded.assy").write_text("links:\n  - part: cube\n")

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    # The geometry is never built: this test only walks the assembly tree.
    (pkg / "cube.py").write_text(
        "import cadquery as cq\n\nshape = cq.Workplane('XY').box(1, 1, 1)\nshow_object(shape)  # noqa: F821\n"
    )

    with _serve(served) as url:
        (pkg / "partcad.yaml").write_text(
            "parts:\n"
            "  cube:\n"
            "    type: cadquery\n"
            "assemblies:\n"
            "  downloaded:\n"
            "    type: assy\n"
            "    fileFrom: url\n"
            "    fileUrl: %s/downloaded.assy\n" % url
        )

        # The package loads even though the ASSY file is not in it yet
        ctx = pc.Context(str(pkg))
        assembly = ctx._get_assembly(":downloaded")
        assert assembly is not None
        assert os.path.exists(assembly.path) is False

        # Instantiating the assembly downloads the ASSY file and follows it
        bom = asyncio.run(assembly.get_bom())
        assert os.path.exists(assembly.path) is True
        assert sum(bom.values()) == 1


def test_file_url_without_url_1(tmp_path):
    """'fileFrom: url' without 'fileUrl' names the object it came from"""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "partcad.yaml").write_text("parts:\n  bolt:\n    type: step\n    fileFrom: url\n")

    with pytest.raises(Exception, match="'bolt' declares 'fileFrom: url' but no 'fileUrl'"):
        pc.Context(str(pkg))
