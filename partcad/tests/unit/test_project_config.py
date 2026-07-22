#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-27
#
# Licensed under Apache License, Version 2.0.
#

import partcad as pc


def test_project_config_version_1():
    """Positive test case for PartCAD version requirement in the package config file"""
    try:
        ctx = pc.Context("partcad/tests/unit/data/project_config_valid_1.yaml")
        # The context is not a package and has no configuration of its own.
        # The parsed configuration belongs to the root package.
        assert ctx.root.config_obj["partcad"] == ">=0.1.0"
    except Exception as e:
        assert False, "Valid configuration file caused an exception: %s" % e


def test_project_config_version_2():
    """Negative test case for PartCAD version requirement in the package config file"""
    try:
        ctx = pc.Context("partcad/tests/unit/data/project_config_invalid_1.yaml")
        assert False, "Invalid configuration file did not cause an exception"
    except:
        _ignore = True


def test_project_config_template():
    ctx = pc.init("partcad/tests/partcad.yaml")
    this = ctx.get_project(pc.ROOT)
    ctx.import_project(
        this,
        {
            "name": "//that",
            "type": "local",
            "path": "unit/data/project_config_template.yaml",
        },
    )
    # In this test case, the template is used to name the part the same name as
    # the package is called.
    part = ctx._get_part("//that://that")
    assert not part is None


def test_project_config_template_override():
    ctx = pc.init("partcad/tests/partcad.yaml")
    this = ctx.get_project(pc.ROOT)
    # Import under a name of its own. pc.init() hands back a process-wide context,
    # so reusing "//that" here would collide with test_project_config_template()
    # above whenever both tests run in the same process, and the outcome would
    # depend on how pytest-xdist happened to distribute them.
    ctx.import_project(
        this,
        {
            "name": "//that_include",
            "type": "local",
            "path": "unit/data/project_config_include.yaml",
            "includePaths": ["subdir"],
        },
    )
    # The part is named by a variable pulled in from the Jinja include, not by
    # the package name.
    part = ctx._get_part("//that_include:defined")
    assert not part is None
