#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The CLI-shaped JSON-RPC method registry.

Method names mirror ``partcad-cli`` subcommands (``inspect.part``,
``export.assembly``, ``list.all``, ``info``, ...). Each maps to a transport-
agnostic operation in :mod:`partcad_service_json_rpc.core.operations`. The
``rpc.discover`` method returns the machine-readable catalog, with each method's
summary taken from the operation's docstring.
"""

import functools

from ..core import operations

# CLI-shaped method name -> operation callable.
_OPERATIONS = {
    "inspect.part": operations.inspect_part,
    "inspect.sketch": operations.inspect_sketch,
    "inspect.interface": operations.inspect_interface,
    "inspect.assembly": operations.inspect_assembly,
    "inspect.file": operations.inspect_file,
    "export.part": operations.export_part,
    "export.assembly": operations.export_assembly,
    "add.part": operations.add_part,
    "add.assembly": operations.add_assembly,
    "add.object": operations.add_object,
    "import.object": operations.import_object,
    "inspect.object": operations.inspect_object,
    "package.path": operations.package_path,
    "package.load": operations.package_load,
    "package.refresh": operations.package_refresh,
    "init": operations.init,
    "list.all": operations.list_all,
    "list.objects": operations.list_objects,
    "list.packages": operations.list_packages,
    "list.providers": operations.list_providers,
    "list.mates": operations.list_mates,
    "bom": operations.bom,
    "search.objects": operations.search_objects,
    "render.objects": operations.render_objects,
    "convert.object": operations.convert_object,
    "adhoc.convert": operations.adhoc_convert,
    "test.run": operations.test_run,
    "lint.run": operations.lint_run,
    "daemon.reset": operations.daemon_reset,
    "daemon.status": operations.daemon_status,
    "daemon.set.telemetry": operations.daemon_set_telemetry,
    "test": operations.test,
    "info": operations.info,
    "info.object": operations.info_object,
    "context.create": operations.context_create,
    "activate": operations.activate,
    "version": operations.version,
    "healthcheck": operations.healthcheck,
    "ensure_loaded": operations.ensure_loaded,
    "install": operations.install,
    "update": operations.update,
}


def _summary(fn) -> str:
    doc = (fn.__doc__ or "").strip()
    return doc.split("\n", 1)[0] if doc else ""


def _begins_a_command(fn):
    """Wrap an operation so that one JSON-RPC request counts as one command.

    PartCAD scopes a few things to "the command now running" -- so far, the
    deadline latch that stops a runaway plugin script from being asked again
    (:mod:`partcad.plugin`). A CLI process runs one command and exits, so
    nothing there has to say where one ends. The daemon serves many, against
    contexts it keeps warm indefinitely, so this is where it says so.

    Wrapping the registry rather than, say, the shared ``_ctx()`` helper: every
    method gets the same treatment whether or not it takes a context, and no
    operation can be written later that quietly skips it.

    Skipped while PartCAD is unimported -- there are no plugins to un-latch yet,
    and a meta method like ``rpc.discover`` should not pay for the import.
    """

    @functools.wraps(fn)
    def begin(session, params):
        partcad = getattr(session, "partcad", None)
        if partcad is not None:
            partcad.plugin.begin_command()
        return fn(session, params)

    return begin


def build_registry() -> dict:
    """Return the full method registry, including the meta method ``rpc.discover``."""
    registry = {name: _begins_a_command(fn) for name, fn in _OPERATIONS.items()}

    def discover(session, params):  # pylint: disable=unused-argument
        return {"methods": [{"name": name, "summary": _summary(fn)} for name, fn in sorted(registry.items())]}

    discover.__doc__ = "List the available JSON-RPC methods and their summaries."
    registry["rpc.discover"] = discover
    return registry
