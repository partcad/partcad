#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import os

import partcad as pc

test_config_import_git = {
    "name": "/part_step",
    "type": "git",
    "url": "https://github.com/partcad/partcad",
    "revision": "devel",
    "relPath": "examples/produce_part_step",
}
test_config_import_tar = {
    "name": "/part_step",
    "type": "tar",
    "url": "https://github.com/partcad/partcad/archive/7544a5a1e3d8909c9ecee9e87b30998c05d090ca.tar.gz",
    "relPath": "partcad-7544a5a1e3d8909c9ecee9e87b30998c05d090ca/examples/part_step",
}


def test_project_this_1():
    ctx = pc.Context("partcad/tests")
    prj = ctx.get_project("/")
    assert prj is not None


def test_project_this_2():
    ctx = pc.Context("examples/produce_part_step")
    prj = ctx.get_project("")
    assert prj is not None


def test_project_this_3():
    ctx = pc.Context("examples")
    prj = ctx.get_project("")
    assert prj is not None


def test_project_import_git1():
    ctx = pc.Context()
    prj = ctx.import_project(None, test_config_import_git)
    assert prj is not None


def test_project_import_git2():
    ctx = pc.Context()
    factory = pc.ProjectFactoryGit(ctx, None, test_config_import_git)
    assert factory.project is not None


def test_project_import_tar1():
    ctx = pc.Context()
    prj = ctx.import_project(None, test_config_import_tar)
    assert prj is not None
    assert os.path.exists(prj.path)


def test_project_import_tar2():
    ctx = pc.Context()
    factory = pc.ProjectFactoryTar(ctx, None, test_config_import_tar)
    assert factory.project is not None
    assert os.path.exists(factory.project.path)
