#!/usr/bin/env python3
#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-14
#
# Licensed under Apache License, Version 2.0.
#

import partcad as pc


def test_package_test_recursive_1():
    """Test all examples without logging actions"""
    ctx = pc.Context("examples")
    examples = ctx.get_project(pc.ROOT)
    assert examples is not None
    assert examples.test(ctx) == True


def test_package_test_async():
    """Test one examples with logging actions on"""
    ctx = pc.Context("examples/provider_manufacturer")
    manufacturer = ctx.get_project(".")
    assert manufacturer is not None
    assert manufacturer.test_log_wrapper(ctx) == True
