#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import os

import pytest
import asyncio
import partcad as pc
from unittest.mock import patch


def test_ctx1():
    ctx = pc.Context("tests/partcad")
    assert ctx is not None


def test_ctx_stats1():
    ctx = pc.Context("examples")
    assert ctx is not None
    ctx.stats_recalc()
    assert ctx.stats_packages > 0
    assert ctx.stats_parts == 0
    ctx.get_project("//produce_part_cadquery_primitive")
    assert ctx.stats_parts > 0
    assert ctx.stats_parts_instantiated == 0
    assert ctx.stats_assemblies == 0
    ctx.get_project("//produce_assembly_assy")
    assert ctx.stats_assemblies > 0
    assert ctx.stats_assemblies_instantiated == 0
    assert ctx.stats_memory > 0


def test_ctx_stats2():
    ctx = pc.Context("examples")
    assert ctx is not None
    ctx.stats_recalc()
    assert ctx.stats_parts_instantiated == 0
    old_memory = ctx.stats_memory

    cube = ctx._get_part("//produce_part_cadquery_primitive:cube")
    assert cube is not None
    assert ctx.stats_parts_instantiated == 0
    ctx.stats_recalc()
    new_memory = ctx.stats_memory
    assert new_memory > old_memory

    old_memory = ctx.stats_memory
    cube.cacheable = False
    obj = asyncio.run(cube.get_wrapped(ctx))
    assert obj is not None
    ctx.stats_recalc()
    assert ctx.stats_parts_instantiated == 1
    new_memory = ctx.stats_memory

    assert new_memory > old_memory


def test_ctx_fini():
    ctx1 = pc.init()
    assert ctx1 is not None
    pc.fini()
    ctx2 = pc.init()
    assert ctx2 is not None
    assert ctx2 != ctx1
    pc.fini()
    ctx3 = pc.init()
    assert ctx3 is not None


@pytest.mark.parametrize("variation", [(True, False), (False, True), (False, False)])
def test_offline_mode(variation):
    offline, force_update = variation

    with patch.object(pc.user_config, "offline", offline), \
        patch.object(pc.user_config, "force_update", force_update):
        ctx = pc.Context(user_config=pc.user_config)
        checks = [
            (0, True, True),          # At time 0, should check connectivity with result of True
            (20, False, True),        # At time 20, should not check connectivity and saved state must return True
            (80, True, False),        # At time 80, should check connectivity with result of False
            (120, False, False),      # At time 120, should not check connectivity and saved state must return False
            (240, False, False),      # At time 240, should not check connectivity and saved state must return False
            (400, True, True)         # At time 400, should check connectivity with result of True
        ]

        for timestamp, should_check_connection, has_connection in checks:
            with patch('time.time', return_value=timestamp), \
              patch.object(ctx, "_check_connectivity", return_value=has_connection) as check_connectivity_mock:
                assert ctx.is_connected() == (has_connection and not offline)
                if (should_check_connection or force_update) and not offline:
                    check_connectivity_mock.assert_called_once()


def test_ctx_root_reports_the_loaded_package():
    """The root package a Context loaded is reachable, and says where it came from.

    This is the contract the PartCAD IDE reports a loaded package with: it needs
    the 'partcad.yaml' that was loaded and whether the load succeeded, and both
    live on 'Context.root', not on the Context. They were once read straight off
    the Context, and when those attributes moved the extension started failing
    silently with "No PartCAD package is detected" - a Context has no
    'config_path' and no 'broken', so reading either raises AttributeError.
    """
    ctx = pc.Context("examples")

    assert not hasattr(ctx, "config_path")
    assert not hasattr(ctx, "broken")

    assert ctx.root is not None
    assert ctx.root.broken is False
    assert ctx.root.config_path.endswith("partcad.yaml")
    assert os.path.isfile(ctx.root.config_path)
    # The name is adopted from the loaded 'partcad.yaml', so it is not the
    # provisional '//' the Context starts out with.
    assert ctx.name != pc.consts.ROOT
    assert ctx.get_project(ctx.name) is ctx.root


# --------------------------------------------------------------------------- #
# What "offline" is decided by                                                 #
# --------------------------------------------------------------------------- #


def test_the_probe_is_a_public_resolver_when_nothing_is_proxied(monkeypatch):
    """The historical answer, and the right one on a host that dials out itself."""
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    assert pc.context.connectivity_probe() == ("8.8.8.8", 53)


@pytest.mark.parametrize(
    "proxy, expected",
    [
        ("http://127.0.0.1:33893", ("127.0.0.1", 33893)),
        ("http://proxy.example.com:3128", ("proxy.example.com", 3128)),
        # No scheme is a spelling people use, and urlparse reads it as a path
        # unless one is supplied.
        ("proxy.example.com:3128", ("proxy.example.com", 3128)),
        # No port either: an HTTP proxy's default.
        ("http://proxy.example.com", ("proxy.example.com", 80)),
        ("http://user:secret@proxy.example.com:8080", ("proxy.example.com", 8080)),
    ],
)
def test_a_proxied_host_is_asked_about_its_proxy(monkeypatch, proxy, expected):
    """Where every packet goes through a proxy, only the proxy can answer.

    8.8.8.8 is unreachable in such an environment while git and every download
    work, so probing it reports offline on a machine that can fetch everything
    PartCAD needs -- and 'is_connected()' gates the clone, so an import is then
    never attempted at all.
    """
    monkeypatch.setenv("HTTPS_PROXY", proxy)
    monkeypatch.delenv("https_proxy", raising=False)
    assert pc.context.connectivity_probe() == expected


def test_the_lowercase_spelling_is_read_too(monkeypatch):
    """'https_proxy' is what most tools set; both spellings are in the wild."""
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("https_proxy", "http://proxy.example.com:3128")
    assert pc.context.connectivity_probe() == ("proxy.example.com", 3128)


def test_an_unparseable_proxy_falls_back_rather_than_failing(monkeypatch):
    """A value with no host in it says nothing, so the resolver answers instead."""
    monkeypatch.setenv("HTTPS_PROXY", "://")
    monkeypatch.delenv("https_proxy", raising=False)
    assert pc.context.connectivity_probe() == ("8.8.8.8", 53)
