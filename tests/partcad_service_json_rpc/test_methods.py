#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the CLI-shaped JSON-RPC method registry."""

import types

from partcad_service_json_rpc.core import operations
from partcad_service_json_rpc.rpc import methods


def test_registry_maps_cli_shaped_names_to_operations():
    """Each entry wraps its operation (see _begins_a_command), so compare the
    wrapped function rather than the entry itself."""
    registry = methods.build_registry()
    assert registry["inspect.part"].__wrapped__ is operations.inspect_part
    assert registry["export.assembly"].__wrapped__ is operations.export_assembly
    assert registry["inspect.object"].__wrapped__ is operations.inspect_object
    assert registry["package.load"].__wrapped__ is operations.package_load
    assert registry["list.all"].__wrapped__ is operations.list_all
    assert registry["info"].__wrapped__ is operations.info
    # What the PartCAD Viewer's tabs beside the 3D one are filled from. Wrapped
    # like every other entry, so the command generation advances for them too.
    assert registry["bom"].__wrapped__ is operations.bom
    assert registry["assembly.guide"].__wrapped__ is operations.assembly_guide
    assert registry["supply.quote"].__wrapped__ is operations.supply_quote


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


# ---- one request is one command ---------------------------------------------
#
# PartCAD scopes its plugin deadline latch to "the command now running". A CLI
# process runs one command and exits; the daemon serves many against contexts it
# keeps warm indefinitely, so the registry is where it says where one ends.


class _FakePlugin(types.SimpleNamespace):
    def __init__(self):
        super().__init__(commands=0)

    def begin_command(self):
        self.commands += 1


def _session_with_partcad(plugin):
    return types.SimpleNamespace(partcad=types.SimpleNamespace(plugin=plugin))


def test_every_request_begins_a_command():
    plugin = _FakePlugin()
    session = _session_with_partcad(plugin)
    wrapped = methods._begins_a_command(lambda session, params: "ok")

    assert wrapped(session, {}) == "ok"
    assert wrapped(session, {}) == "ok"

    assert plugin.commands == 2


def test_an_unloaded_partcad_is_not_imported_just_to_begin_a_command():
    """A method must not pay for an import it does not need -- and with no
    PartCAD loaded there are no plugins to un-latch anyway."""
    wrapped = methods._begins_a_command(lambda session, params: "ok")

    # Both spellings of "not loaded": the attribute set to None, and unset.
    assert wrapped(types.SimpleNamespace(partcad=None), {}) == "ok"
    assert wrapped(types.SimpleNamespace(), {}) == "ok"


def test_the_command_begins_before_the_operation_runs():
    """A latch set by the previous request must already be stale by the time the
    operation asks a plugin anything -- not cleared on the way out."""
    plugin = _FakePlugin()
    session = _session_with_partcad(plugin)
    seen = []

    wrapped = methods._begins_a_command(lambda session, params: seen.append(plugin.commands))
    wrapped(session, {})

    assert seen == [1]


def test_wrapping_keeps_the_docstring_rpc_discover_advertises():
    """_summary() reads __doc__ off the registry entry, so the wrapper must keep it."""
    registry = methods.build_registry()
    assert registry["info"].__doc__ == operations.info.__doc__
    assert methods._summary(registry["info"])
