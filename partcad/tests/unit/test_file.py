#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-04-17
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import os

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

    wrapped = asyncio.run(bolt.get_wrapped())
    assert wrapped is not None

    assert os.path.exists(bolt.path) is True
    os.unlink(bolt.path)
