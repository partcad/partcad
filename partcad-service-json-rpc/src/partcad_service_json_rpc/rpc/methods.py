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
    "ai.regenerate": operations.ai_regenerate,
    "ai.change": operations.ai_change,
    "add.part": operations.add_part,
    "add.assembly": operations.add_assembly,
    "package.path": operations.package_path,
    "package.load": operations.package_load,
    "package.refresh": operations.package_refresh,
    "init": operations.init,
    "list.all": operations.list_all,
    "list.objects": operations.list_objects,
    "list.packages": operations.list_packages,
    "list.providers": operations.list_providers,
    "list.mates": operations.list_mates,
    "search.objects": operations.search_objects,
    "config.show": operations.config_show,
    "render.objects": operations.render_objects,
    "convert.object": operations.convert_object,
    "adhoc.convert": operations.adhoc_convert,
    "test": operations.test,
    "info": operations.info,
    "info.object": operations.info_object,
    "context.create": operations.context_create,
    "activate": operations.activate,
    "prompt.respond": operations.prompt_respond,
    "version": operations.version,
    "healthcheck": operations.healthcheck,
    "ensure_loaded": operations.ensure_loaded,
    "install": operations.install,
    "update": operations.update,
}


def _summary(fn) -> str:
    doc = (fn.__doc__ or "").strip()
    return doc.split("\n", 1)[0] if doc else ""


def build_registry() -> dict:
    """Return the full method registry, including the meta method ``rpc.discover``."""
    registry = dict(_OPERATIONS)

    def discover(session, params):  # pylint: disable=unused-argument
        return {"methods": [{"name": name, "summary": _summary(fn)} for name, fn in sorted(registry.items())]}

    discover.__doc__ = "List the available JSON-RPC methods and their summaries."
    registry["rpc.discover"] = discover
    return registry
