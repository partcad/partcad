#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2023-12-27
#
# Licensed under Apache License, Version 2.0.
#

import partcad as pc


def test_project_config_version_1():
    """Positive test case for PartCAD version requirement in the package config file"""
    try:
        ctx = pc.Context("partcad/tests/unit/data/project_config_valid_1.yaml")
        assert ctx.config_obj["partcad"] == ">=0.1.0"
    except Exception as e:
        assert False, "Valid configuration file caused an exception: %s" % e


def test_project_config_version_2():
    """Negative test case for PartCAD version requirement in the package config file"""
    try:
        ctx = pc.Context(
            "partcad/tests/unit/data/project_config_invalid_1.yaml"
        )
        assert False, "Invalid configuration file did not cause an exception"
    except:
        _ignore = True


def test_project_config_template():
    ctx = pc.init("partcad/tests/partcad.yaml")
    this = ctx.get_project(pc.ROOT)
    ctx.import_project(
        this,
        {
            "name": "/that",
            "type": "local",
            "path": "unit/data/project_config_template.yaml",
        },
    )
    # In this test case, the template is used to name the part the same name as
    # the package is called.
    part = ctx._get_part("/that:/that")
    assert not part is None


def test_project_config_template_override():
    ctx = pc.init("partcad/tests/partcad.yaml")
    this = ctx.get_project(pc.ROOT)
    ctx.import_project(
        this,
        {
            "name": "/that",
            "type": "local",
            "path": "unit/data/project_config_include.yaml",
            "includePaths": ["subdir"],
        },
    )
    # In this test case, the template is used to name the part the same name as
    # the package is called.
    part = ctx._get_part("/that:defined")
    assert not part is None
