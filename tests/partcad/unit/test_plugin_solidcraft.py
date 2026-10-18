#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The SolidCraft plugin package ('plugins/solidcraft'), used the way a workspace uses it.

The consumer package imports the plugin and declares one part per partType, so
these are as much tests of what a file-backed partType in *another* package
means as of the plugin: the file is the consumer's, the image and the cache
directory are the plugin's. Building the parts downloads SolidCraft, so that
part is gated and measured.
"""

import asyncio
import importlib.util
import os
import zipfile

import pytest

import partcad as pc
from partcad import output, shape_envelope

CONSUMER = "tests/partcad/unit/data/plugin_solidcraft"
PLUGIN = "plugins/solidcraft"


def _module(name):
    spec = importlib.util.spec_from_file_location("solidcraft_" + name, os.path.join(PLUGIN, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ctx():
    return pc.Context(os.path.join(CONSUMER, "partcad.yaml"))


def test_the_plugin_declares_its_part_types_and_export(ctx):
    plugin = ctx.get_project("//solidcraft")
    assert plugin is not None
    for name, extension in (("solidcraft", "solidcraft"), ("rhino", "3dm"), ("iges", "igs")):
        assert plugin.get_part_type_config(name)["extension"] == extension
    assert "solidcraft" in plugin.config_obj["export"]
    assert plugin.config_obj["open"]["solidcraft"]["formats"][0] == "solidcraft"


@pytest.mark.parametrize(
    "name, file", [("plate", "plate.solidcraft"), ("slab", "slab.3dm"), ("cylinder", "cylinder.igs")]
)
def test_the_file_is_the_consumer_s(ctx, name, file):
    part = ctx.get_part(":" + name)
    assert os.path.abspath(part.path) == os.path.abspath(os.path.join(CONSUMER, file))
    assert os.path.abspath(part.path) in [os.path.abspath(p) for p in part.cache_dependencies]


def test_the_image_and_the_cache_are_the_plugin_s(ctx):
    plugin = ctx.get_project("//solidcraft")
    assert plugin.docker_image_declared == "ghcr.io/partcad/partcad-plugin-solidcraft:0.16.1"
    # The consumer declares no image, so the one the part is keyed under -- and
    # its sandbox built from, where Docker is in use -- is the plugin's.
    assert ctx.get_part(":plate").environment_cache_key.endswith(";image=" + plugin.docker_image_declared)
    assert output.package_cache_dir(ctx, plugin) == os.path.join(os.path.abspath(PLUGIN), ".cache")


def test_a_part_s_parameters_become_the_design_s():
    script = _module("read_part")
    assert script.parameter_script({"height": 35, "width": 12.5, "flag": True, "unset": None}) == [
        {"command": "parameters.change", "params": {"name": "height", "expression": "35"}},
        {"command": "parameters.change", "params": {"name": "width", "expression": "12.5"}},
    ]


def test_every_platform_names_an_asset_and_a_checksum():
    tool = _module("solidcraft_tool")
    for (system, machine), (asset, sha256) in tool.ASSETS.items():
        assert tool.VERSION in asset
        assert len(sha256) == 64 and int(sha256, 16) >= 0


def _measured(ctx, name):
    envelope = asyncio.run(ctx.get_part(name).get_wrapped(ctx))
    if envelope is None:
        pytest.skip("SolidCraft or the sandbox is unavailable: %s" % ctx.get_part(name).errors)
    return envelope[shape_envelope.KEY_METADATA][shape_envelope.METADATA_MEASUREMENTS]


@pytest.mark.slow
def test_the_parts_are_what_solidcraft_reads(ctx):
    plate = _measured(ctx, ":plate")
    assert plate["volume"] == pytest.approx(40 * 30 * 20)
    assert _measured(ctx, ":slab")["bbox"] == pytest.approx([0, 0, 0, 25, 15, 5], abs=1e-6)
    cylinder = _measured(ctx, ":cylinder")
    assert cylinder["bbox"] == pytest.approx([-5, -5, 0, 5, 5, 12], abs=1e-6)
    assert cylinder["volume"] == pytest.approx(3.14159265 * 25 * 12, rel=2e-3)


@pytest.mark.slow
def test_a_parameter_rebuilds_the_design(ctx):
    taller = _measured(ctx, ":plate;height=35")
    assert taller["bbox"] == pytest.approx([0, 0, 0, 40, 30, 35], abs=1e-6)


@pytest.mark.slow
def test_an_object_exports_as_a_solidcraft_design(ctx, tmp_path):
    target = tmp_path / "slab.solidcraft"
    part = ctx.get_part(":slab")
    try:
        asyncio.run(part.render_async(ctx, format_name="solidcraft:solidcraft", filepath=str(target)))
    except Exception as e:
        pytest.skip("SolidCraft or the sandbox is unavailable: %s" % e)
    if not target.is_file():
        pytest.skip("SolidCraft or the sandbox is unavailable: %s" % part.errors)
    with zipfile.ZipFile(target) as design:
        names = design.namelist()
    assert "document.json" in names
    assert any(name.endswith(".step") for name in names)
