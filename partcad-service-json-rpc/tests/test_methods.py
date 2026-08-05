#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the CLI-shaped JSON-RPC method registry."""

from partcad_service_json_rpc.core import operations
from partcad_service_json_rpc.rpc import methods


def test_registry_maps_cli_shaped_names_to_operations():
    registry = methods.build_registry()
    assert registry["inspect.part"] is operations.inspect_part
    assert registry["export.assembly"] is operations.export_assembly
    assert registry["add.object"] is operations.add_object
    assert registry["package.load"] is operations.package_load
    assert registry["list.all"] is operations.list_all
    assert registry["info"] is operations.info


def test_every_registry_entry_is_callable():
    registry = methods.build_registry()
    assert registry
    assert all(callable(fn) for fn in registry.values())


def test_rpc_discover_is_registered_and_lists_methods_with_summaries():
    registry = methods.build_registry()
    assert "rpc.discover" in registry
    catalog = registry["rpc.discover"](session=None, params={})
    names = {entry["name"] for entry in catalog["methods"]}
    assert "inspect.part" in names
    assert "rpc.discover" in names
    inspect_entry = next(e for e in catalog["methods"] if e["name"] == "inspect.part")
    assert inspect_entry["summary"]  # non-empty, taken from the docstring
