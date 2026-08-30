#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Transport-agnostic PartCAD operations.

Each operation takes ``(session, params)``, performs PartCAD work through the
session's context, emits events through the session's emitter, and returns a
JSON-serializable result (or ``None``). The behavior mirrors the legacy VS Code
LSP server one-to-one so both backends stay identical; only the parameter shape
is normalized to named JSON-RPC params. Operations that require a loaded context
silently no-op when none is loaded, exactly as the legacy server did.
"""

import hashlib
import math
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import yaml
from packaging.specifiers import SpecifierSet

from ..rpc.dispatcher import JsonRpcError
from . import events

# PartCAD-specific JSON-RPC error code: a partcad.yaml could not be parsed. The
# CLI turns this into its "Invalid configuration file" message + exit code.
INVALID_CONFIG = -32001
# A user/usage error (bad argument, object not found, unsupported conversion).
# The CLI turns this into click.UsageError (exit code 2), matching the old
# in-process commands.
USAGE_ERROR = -32002


def _ctx(session, params):
    """Return the context this request operates on.

    Context-aware operations carry a ``context`` id (from ``context.create``);
    the daemon persists these indefinitely. When absent (e.g. the VS Code
    extension's single-context flow), fall back to the session's default
    context.
    """
    context_id = params.get("context")
    if context_id is not None:
        ctx = session.contexts.get(context_id)
        if ctx is None:
            # A stale id (daemon restarted since the client got it, or -- once
            # the eviction TODO in context_create lands -- an expired context).
            # Report it rather than no-op silently: the caller cannot otherwise
            # tell "unknown context" from "nothing to do".
            raise JsonRpcError(USAGE_ERROR, "Unknown context: %s" % context_id)
        return ctx
    return session.partcad_ctx


def _qualified(package: str, name: str) -> str:
    return package + ":" + name


def _resolve_object(ctx, pc, params):
    """The ``(package, name)`` of the object a request names.

    ``package`` is the package that *owns* the object, which is not always the
    one the request selected: an object given as ``//other/package:name`` is
    produced there, whatever ``--package`` said. Returns ``None`` when the
    selected package is not loaded, having said so, the way every other
    context-aware operation reports it.
    """
    object_name = params.get("object")
    if not object_name:
        raise JsonRpcError(USAGE_ERROR, "No object is given")

    package = ctx.resolve_package_path(params.get("package") or ".")
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None

    return pc.utils.resolve_resource_path(package_obj.name, object_name)


def _root_config_path(ctx) -> str:
    """The path of the ``partcad.yaml`` a context loaded as its root package.

    A ``Context`` has neither ``config_path`` nor ``broken``: both belong to the
    root ``Project`` it loaded, reachable as ``Context.root``. Reading them off
    the context raises ``AttributeError`` -- which is what made the extension
    report "No PartCAD package is detected" for a package that had in fact
    loaded perfectly. Guarding the attribute with ``getattr(..., "broken",
    False)`` does not help either: the guard then always says "not broken" and
    the very next line still raises.

    Raises if the root package did not load, so the caller reports why.
    """
    root = getattr(ctx, "root", None)
    if root is None or root.broken:
        raise Exception("Package configuration file is not found or is not valid")
    return root.config_path


# ---- inspection ------------------------------------------------------------


def inspect_part(session, params):
    """Instantiate and show a part in the connected CAD viewer."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    package, name = params["package"], params["name"]
    with session.partcad.logging.Process("Inspect", package, name):
        part = ctx.get_part(_qualified(package, name), params.get("params"))
        if part:
            part.show()
    session.emitter.signal(events.SHOW_PART_DONE)
    return None


def inspect_sketch(session, params):
    """Instantiate and show a sketch."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    package, name = params["package"], params["name"]
    with session.partcad.logging.Process("Inspect", package, name):
        sketch = ctx.get_sketch(_qualified(package, name), params.get("params"))
        if sketch:
            sketch.show()
    session.emitter.signal(events.SHOW_PART_DONE)
    return None


def inspect_interface(session, params):
    """Instantiate and show an interface."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    package, name = params["package"], params["name"]
    with session.partcad.logging.Process("Inspect", package, name):
        interface = ctx.get_interface(_qualified(package, name))
        if interface:
            interface.show()
    session.emitter.signal(events.SHOW_PART_DONE)
    return None


def inspect_assembly(session, params):
    """Instantiate and show an assembly."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    package, name = params["package"], params["name"]
    with session.partcad.logging.Process("Inspect", package, name):
        assembly = ctx.get_assembly(_qualified(package, name), params.get("params"))
        if assembly:
            assembly.show()
    session.emitter.signal(events.SHOW_PART_DONE)
    return None


def inspect_file(session, params):
    """Find the object defined by a file path and ask the client to inspect it."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    path = params.get("path", "")
    if path == "":
        path = _root_config_path(ctx)
    _inspect_by_path(session, ctx, path)
    return None


def _instances_of(objects, name):
    """The cache keys under which ``name`` (and only ``name``) is instantiated.

    ``Project.get_object()`` keys a parameterized instance as
    ``"<name>;<param>=<value>,..."`` (see ``result_name`` in
    ``src/partcad/project.py``), so ``";"`` is what separates an object
    from its parameters here; ``":"`` separates a *package* from an object and
    never appears in these per-project dicts. Matching a bare prefix instead
    would evict unrelated siblings (``bracket_v2`` when ``bracket`` was saved),
    and matching ``name + ":"`` would evict no parameterized instance at all.

    Returns a list, not a generator: the caller deletes these from ``objects``.
    """
    return [n for n in objects if n == name or n.startswith(name + ";")]


def _inspect_by_path(session, ctx, path):
    # The context comes from the caller: a request carrying a `context` id
    # must be served by that context, not by whichever one happens to be the
    # session default.
    with session.partcad.logging.Process("InspectFile", path):
        for prj_name, prj in ctx.projects.items():
            for name, assy in prj.assemblies.items():
                if hasattr(assy, "orig_name") and assy.name != assy.orig_name:
                    continue
                if assy.path is not None and os.path.exists(assy.path) and os.path.samefile(assy.path, path):
                    for paramed in _instances_of(prj.assemblies, name):
                        del prj.assemblies[paramed]
                    session.emitter.emit(
                        events.EXECUTE,
                        {"command": "partcad.inspectAssembly", "args": [{"name": name, "pkg": prj_name}, {}, True]},
                    )
                    return
            for name, part in prj.parts.items():
                if hasattr(part, "orig_name") and part.name != part.orig_name:
                    continue
                if part.path is not None and os.path.exists(part.path) and os.path.samefile(part.path, path):
                    for paramed in _instances_of(prj.parts, name):
                        del prj.parts[paramed]
                    session.emitter.emit(
                        events.EXECUTE,
                        {"command": "partcad.inspectPart", "args": [{"name": name, "pkg": prj_name}, {}, True]},
                    )
                    return
            for name, sketch in prj.sketches.items():
                if hasattr(sketch, "orig_name") and sketch.name != sketch.orig_name:
                    continue
                if sketch.path is not None and os.path.exists(sketch.path) and os.path.samefile(sketch.path, path):
                    if name in prj.sketches:
                        prj.sketches[name].shape = None
                        prj.sketches[name].components = []
                    for paramed in _instances_of(prj.sketches, name):
                        del prj.sketches[paramed]
                    session.emitter.emit(
                        events.EXECUTE,
                        {"command": "partcad.inspectSketch", "args": [{"name": name, "pkg": prj_name}, {}, True]},
                    )
                    return


# ---- export ----------------------------------------------------------------


def export_part(session, params):
    """Render a part to a file."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    package, name = params["package"], params["name"]
    with session.partcad.logging.Process("Export", package, name):
        part = ctx.get_part(_qualified(package, name), params.get("params"))
        if part:
            part.render(ctx, params["type"], filepath=params["path"])
    session.emitter.signal(events.EXPORT_PART_DONE)
    return None


def export_assembly(session, params):
    """Render an assembly to a file."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    package, name = params["package"], params["name"]
    with session.partcad.logging.Process("Export", package, name):
        assembly = ctx.get_assembly(_qualified(package, name), params.get("params"))
        if assembly:
            assembly.render(ctx, params["type"], filepath=params["path"])
    session.emitter.signal(events.EXPORT_PART_DONE)
    return None


# ---- authoring -------------------------------------------------------------


def add_part(session, params):
    """Add a part to a package from an existing file."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    kind, path, package = params["kind"], params["path"], params["package"]
    config = params.get("config", {})
    session.emitter.info("Adding %s using the file %s" % (kind, path))
    with session.partcad.logging.Process("AddPart", path):
        project = ctx.get_project(package)
        project.add_part(kind, path, config)
    return None


def add_assembly(session, params):
    """Add an assembly to a package from an existing file."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    kind, path, package = params["kind"], params["path"], params["package"]
    session.emitter.info("Adding assembly %s" % path)
    with session.partcad.logging.Process("AddAssy", path):
        project = ctx.get_project(package)
        project.add_assembly(kind, path)
    return None


def _invalidate_context(session, params):
    """Drop the cached context after a mutation so the next command re-reads it.

    PartCAD writes configuration changes straight to ``partcad.yaml`` without
    refreshing the live in-memory project registry, and the daemon keeps
    contexts warm indefinitely -- so a mutated context would keep serving the
    pre-mutation contents (``pc add part x`` followed by ``pc list parts``
    showing nothing). Evicting it makes the next ``context.create`` -- which the
    CLI issues before every command -- rebuild it from disk. This is why a
    package-mutating command has to be served by the daemon rather than run in
    the client: a client-side mutation is invisible to the warm context.
    """
    context_id = params.get("context")
    if context_id is None:
        return
    evicted = session.contexts.pop(context_id, None)
    session.context_user_configs.pop(context_id, None)
    if evicted is not None and session.partcad_ctx is evicted:
        session.partcad_ctx = None


def add_object(session, params):
    """Add an existing part or assembly to a package (by reference, no copy).

    The CLI resolves ``path`` to an absolute path (it and the daemon do not
    share a working directory); ``Project._validate_path`` rejects anything
    outside the package, and messages report the path relative to the package.
    """
    from pathlib import Path

    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    obj_kind = params.get("obj_kind", "part")
    package = ctx.resolve_package_path(params.get("package") or ".")
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None

    path = params["path"]
    if not Path(path).exists():
        raise JsonRpcError(USAGE_ERROR, "ERROR: The part file '%s' does not exist." % package_obj.rel_path(path))

    config = {}
    if params.get("desc"):
        config["desc"] = params["desc"]

    try:
        if obj_kind == "part":
            from partcad.actions.part import add_part_action

            added = add_part_action(package_obj, params["kind"], path, config)
        else:
            with pc.logging.Process("AddAssy", package_obj.name):
                added = package_obj.add_assembly(params["kind"], path)
                if added:
                    Path(path).touch()
    finally:
        _invalidate_context(session, params)
    # Only report a name when the object was actually added, so the CLI does not
    # announce success for a rejected path (e.g. one outside the package).
    return {"name": Path(path).stem} if added else None


def import_object(session, params):
    """Import a part or assembly into a package, copying (and maybe converting) it.

    Served by the daemon rather than the client because the work runs through
    sandboxed wrappers: importing an assembly drives ``wrapper_import_assy`` or
    ``wrapper_import_urdf`` in a Python runtime, and ``--target-format``
    converts through the same machinery. Those runtimes belong to the daemon's
    environment and need not exist on the client side at all.
    """
    from pathlib import Path

    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    obj_kind = params.get("obj_kind", "part")
    source = params["source"]
    if not Path(source).exists():
        raise JsonRpcError(USAGE_ERROR, "File '%s' not found." % source)

    package = ctx.resolve_package_path(params.get("package") or ".")
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None

    name = Path(source).stem
    config = {"desc": params["desc"]} if params.get("desc") else {}

    try:
        if obj_kind == "part":
            from partcad.actions.part import import_part_action

            part_type = params["part_type"]
            try:
                import_part_action(package_obj, part_type, name, source, config, params.get("target_format"))
                pc.logging.info("Successfully imported part: %s" % name)
            except Exception as e:  # pylint: disable=broad-except
                pc.logging.exception("Error importing part '%s' (%s)" % (name, part_type))
                raise JsonRpcError(USAGE_ERROR, "Error importing part '%s' (%s): %s" % (name, part_type, e)) from e
            return {"name": name}

        from partcad.actions.assembly import import_assy_action

        try:
            name = import_assy_action(package_obj, params["assembly_type"], source, config)
        except Exception as e:  # pylint: disable=broad-except
            pc.logging.exception("Error importing assembly")
            raise JsonRpcError(USAGE_ERROR, "Error importing assembly: %s" % e) from e
        return {"name": name}
    finally:
        _invalidate_context(session, params)


# ---- package helpers -------------------------------------------------------


def package_path(session, params):
    """Resolve a package's directory and hand it back to a client callback."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    package = params["package"]
    callback = params["callback"]
    project = ctx.get_project(package)
    if not project:
        session.emitter.error(f"Failed to locate the package {package}")
        return None
    session.emitter.emit(
        events.EXECUTE,
        {
            "command": callback,
            "args": [
                {
                    "packageName": package,
                    "packagePath": project.path,
                    "isAbsolute": os.path.isabs(project.path),
                }
            ],
        },
    )
    return None


def test(session, params):
    """Run PartCAD tests for a package or a single object."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    package = params["package"]
    object_name = params.get("object", "")

    if object_name == "":
        with session.partcad.logging.Process("Test", package):
            all_packages = ctx.get_all_packages(parent_name=package, has_stuff=True)
            for pkg_name in [p["name"] for p in all_packages]:
                with session.partcad.logging.Action("Test", pkg_name):
                    ctx.projects[pkg_name].test_log_wrapper(ctx)
        return None

    project = ctx.get_project(package)
    if not project:
        session.emitter.error("Failed to get the package: %s" % str(package))
        return None
    if project.get_interface_config(object_name):
        obj = project.get_interface(object_name)
    elif project.get_sketch_config(object_name):
        obj = project.get_sketch(object_name)
    elif project.get_part_config(object_name):
        obj = project.get_part(object_name)
    elif project.get_assembly_config(object_name):
        obj = project.get_assembly(object_name)
    else:
        session.emitter.error(f"Object {object_name} is not found in {package}")
        return None

    if obj:
        with session.partcad.logging.Process("Test", object_name):
            obj.test_log_wrapper(ctx)
    return None


def info(session, params):
    """Report package statistics (the getStats operation)."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    cwd = os.getcwd()
    path = _root_config_path(ctx)
    if path.startswith(cwd):
        path = path.replace(cwd, ".")
    ctx.stats_recalc()
    session.emitter.emit(
        events.STATS,
        {
            "stats": {
                "path": path,
                "packages": ctx.stats_packages,
                "packagesInstantiated": ctx.stats_packages_instantiated,
                "sketches": ctx.stats_sketches,
                "sketchesInstantiated": ctx.stats_sketches_instantiated,
                "interfaces": ctx.stats_interfaces,
                "interfacesInstantiated": ctx.stats_interfaces_instantiated,
                "parts": ctx.stats_parts,
                "partsInstantiated": ctx.stats_parts_instantiated,
                "assemblies": ctx.stats_assemblies,
                "assembliesInstantiated": ctx.stats_assemblies_instantiated,
                "size": ctx.stats_memory,
            },
            "version": session.partcad.__version__,
        },
    )
    return None


def info_object(session, params):
    """Show detailed information about a part, assembly, interface, or sketch.

    Ported verbatim from the CLI `info` command: with no object name it reports
    the package's info, otherwise the object's configuration and info. Output is
    emitted through PartCAD logging so it renders exactly as before.
    """
    from pprint import pformat

    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad

    package = params.get("package")
    object_name = params.get("object")
    param_list = list(params.get("params") or [])

    if object_name is None:
        package_name = ctx.resolve_package_path(package)
        package_obj = ctx.get_project(package_name)
        if not package_obj:
            pc.logging.error("Package %s is not found" % package_name)
            return None
        for k, v in package_obj.info().items():
            pc.logging.info("INFO: %s: %s" % (k, pformat(v)))
        return None

    package, object_name = pc.utils.resolve_resource_path(ctx.get_current_project_path(), object_name)
    path = "%s:%s" % (package, object_name)

    if params.get("assembly"):
        obj = ctx.get_assembly(path, params=param_list)
    elif params.get("interface"):
        obj = ctx.get_interface(path)
    elif params.get("sketch"):
        obj = ctx.get_sketch(path, params=param_list)
    else:
        obj = ctx.get_part(path, params=param_list)

    if obj is None:
        pc.logging.error("Object %s not found" % path)
    else:
        pc.logging.info("CONFIGURATION: %s" % pformat(obj.config))
        for k, v in obj.info().items():
            pc.logging.info("INFO: %s: %s" % (k, pformat(v)))
    return None


def adhoc_convert(session, params):
    """Convert a CAD or sketch file between formats, ad-hoc (no package/context).

    A pure file operation: input/output paths are already absolute (resolved by
    the CLI against the user's cwd). Missing types are inferred from extensions.
    """
    from pathlib import Path

    pc = session.ensure_partcad()
    kind = params.get("kind", "part")
    if kind == "part":
        from partcad.adhoc.convert import convert_cad_file as convert_fn
        from partcad.shape import PART_EXTENSION_MAPPING as mapping
    else:
        from partcad.adhoc.convert import convert_sketch_file as convert_fn
        from partcad.shape import SKETCH_EXTENSION_MAPPING as mapping

    input_path = Path(params["input_filename"])
    output_filename = params.get("output_filename")
    output_path = Path(output_filename) if output_filename else None

    ext_to_type = {".%s" % v: k for k, v in mapping.items()}
    input_type = params.get("input_type") or ext_to_type.get(input_path.suffix.lower())
    output_type = params.get("output_type") or (ext_to_type.get(output_path.suffix.lower()) if output_path else None)

    # Sketch conversion says "input sketch type"; part conversion says
    # "input type" (matches the per-command CLI messages on devel, which the
    # behave scenarios assert on).
    noun = "sketch type" if kind == "sketch" else "type"
    if not input_type:
        pc.logging.error("Cannot infer input %s. Please specify --input explicitly." % noun)
        return None
    if not output_type:
        pc.logging.error("Cannot infer output %s. Please specify --output explicitly." % noun)
        return None
    if output_path is None:
        output_path = input_path.with_suffix(".%s" % mapping[output_type])

    try:
        pc.logging.info("Converting %s (%s) to %s (%s)..." % (input_path, input_type, output_path, output_type))
        convert_fn(str(input_path), input_type, str(output_path), output_type)
        pc.logging.info("Conversion complete: %s" % output_path)
    except ValueError as e:
        # A format that only means anything inside a package ('.urdf', '.assy')
        # is inferable from the filename, so it reaches here even though the
        # CLI's choices exclude it. That is a usage error, not a failed
        # conversion: nothing was attempted and nothing could have been.
        raise JsonRpcError(USAGE_ERROR, str(e))
    except Exception as e:  # pylint: disable=broad-except
        pc.logging.error("Failed to convert: %s" % e)
    return None


async def _test_async(ctx, pc, packages, filter_prefix, sketch, interface, assembly, scene, object_name):
    import asyncio

    from partcad.test.all import tests as all_tests

    tasks = []
    tests_to_run = all_tests(pc.user_config.threads_max)
    if filter_prefix:
        tests_to_run = list(filter(lambda t: t.name.startswith(filter_prefix), tests_to_run))

    for package in packages:
        obj = object_name
        if obj:
            package, obj = pc.utils.resolve_resource_path(ctx.get_current_project_path(), obj)
        prj = ctx.get_project(package)
        if not obj:
            tasks.append(prj.test_log_wrapper_async(ctx, tests=tests_to_run))
        elif interface:
            shape = prj.get_interface(obj)
            if shape is None:
                pc.logging.error("%s is not found" % obj)
            elif not shape.finalized:
                pc.logging.warning("%s is not finalized" % obj)
            else:
                tasks.append(shape.test_async())
        else:
            if sketch:
                shape = prj.get_sketch(obj)
            elif assembly:
                shape = prj.get_assembly(obj)
            else:
                # Awaited, not 'get_part()': this is a coroutine, and a part a
                # URDF or STEP assembly produces has to have that assembly
                # built before it exists. See 'Project.get_part_async()'.
                shape = await prj.get_part_async(obj)
            if shape is None:
                pc.logging.error("%s is not found" % obj)
            elif not shape.finalized:
                pc.logging.warning("%s is not finalized" % obj)
            else:
                tasks.extend([t.test_log_wrapper(tests_to_run, ctx, shape) for t in tests_to_run])

    await asyncio.gather(*tasks)


def test_run(session, params):
    """Run PartCAD tests on a part/assembly/sketch/interface or a whole package."""
    import asyncio

    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    package = ctx.resolve_package_path(params.get("package") or ".")
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name

    with pc.logging.Process("Test", package):
        if params.get("recursive"):
            all_packages = ctx.get_all_packages(parent_name=package)
            if ctx.stats_git_ops:
                pc.logging.info("Git operations: %s" % ctx.stats_git_ops)
            packages = [p["name"] for p in all_packages]
        else:
            packages = [package]
        asyncio.run(
            _test_async(
                ctx,
                pc,
                packages,
                params.get("filter"),
                params.get("sketch"),
                params.get("interface"),
                params.get("assembly"),
                params.get("scene"),
                params.get("object"),
            )
        )
    return None


async def _lint_async(ctx, pc, packages, filter_prefix):
    import asyncio

    from partcad.lint.all import get_linting_checks

    tasks = []
    lint_checks = get_linting_checks(pc.user_config.threads_max)
    if filter_prefix:
        lint_checks = list(filter(lambda l: l.name.startswith(filter_prefix), lint_checks))

    for package in packages:
        prj = ctx.get_project(package)
        tasks.extend([l.lint_log_wrapper(ctx, prj, t) for l in lint_checks for t in l.get_targets(ctx, prj)])
    await asyncio.gather(*tasks)


def lint_run(session, params):
    """Run linting checks on files within a package (recursively when asked)."""
    import asyncio

    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    package = ctx.resolve_package_path(params.get("package") or "")
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name

    with pc.logging.Process("Lint", package):
        if params.get("recursive"):
            all_packages = ctx.get_all_packages(parent_name=package)
            if ctx.stats_git_ops:
                pc.logging.info("Git operations: %s" % ctx.stats_git_ops)
            packages = [p["name"] for p in all_packages]
        else:
            packages = [package]
        asyncio.run(_lint_async(ctx, pc, packages, params.get("filter")))
    return None


def daemon_reset(session, params):
    """Reset the daemon's internal state (cached repos, sandboxes, filesystem cache).

    This is the daemon-side counterpart of `pc system reset`, which only ever
    touches the machine the CLI runs on. The daemon owns its own internal state
    directory and the warm contexts that reference it, so the context registry
    is cleared too and later commands rebuild from clean state.

    Runs unconditionally: the caller has already decided, and a background
    daemon has nobody to ask for confirmation.
    TODO: restrict this with some form of access control. It wipes state on
    behalf of whoever can reach the socket, which is fine while the daemon is
    per-user and local, and is not once it is reachable over HTTP or remotely.
    """
    import shutil

    pc = session.ensure_partcad()
    user_config = pc.user_config
    repo_only = params.get("repo_only", False)
    sandbox_only = params.get("sandbox_only", False)
    cache_only = params.get("cache_only", False)

    with pc.logging.Process("Reset", "global"):
        if repo_only or not (cache_only or sandbox_only):
            for import_type in ("git", "tar"):
                cache_dir = os.path.join(user_config.internal_state_dir, import_type)
                if os.path.exists(cache_dir):
                    with pc.logging.Action("Repos", import_type):
                        shutil.rmtree(cache_dir)
                        pc.logging.info("Removed cached %s dependencies: '%s'" % (import_type, cache_dir))

        if sandbox_only or not (repo_only or cache_only):
            sandbox_dir = os.path.join(user_config.internal_state_dir, "sandbox")
            if os.path.exists(sandbox_dir):
                for subdir in os.listdir(sandbox_dir):
                    with pc.logging.Action("Sandbox", subdir):
                        shutil.rmtree(os.path.join(sandbox_dir, subdir))
                        pc.logging.info("Removed sandbox: '%s'" % subdir)

        if cache_only or not (repo_only or sandbox_only):
            cache_dir = os.path.join(user_config.internal_state_dir, "cache")
            if os.path.exists(cache_dir):
                for subdir in os.listdir(cache_dir):
                    with pc.logging.Action("cache", subdir):
                        shutil.rmtree(os.path.join(cache_dir, subdir))
                        pc.logging.info("Removed cache: '%s'" % subdir)

    # The warm contexts now reference deleted directories; drop them.
    session.contexts.clear()
    session.context_user_configs.clear()
    session.partcad_ctx = None
    return None


def daemon_status(session, params):
    """Report the daemon's version and internal storage usage.

    The daemon-side counterpart of `pc system status`, which reports the same
    for the machine the CLI runs on. The two coincide while the daemon is local;
    they will not once it can be remote, which is why both exist.
    """
    pc = session.ensure_partcad()
    root = pc.user_config.internal_state_dir

    def _dir_size(path):
        total = 0
        for dirpath, _dirnames, filenames in os.walk(path):
            for name in filenames:
                fp = os.path.join(dirpath, name)
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
        return total / 1048576.0

    with pc.logging.Process("Status", "global"):
        pc.logging.info("PartCAD version: %s" % pc.__version__)
        pc.logging.info("Internal data storage location: %s" % root)
        with pc.logging.Action("Status", "total"):
            pc.logging.info("Total internal data storage size: %.2fMB" % _dir_size(root))
        with pc.logging.Action("Status", "git"):
            pc.logging.info("Git cache size: %.2fMB" % _dir_size(os.path.join(root, "git")))
        with pc.logging.Action("Status", "tar"):
            pc.logging.info("Tar cache size: %.2fMB" % _dir_size(os.path.join(root, "tar")))
        with pc.logging.Action("Status", "sandbox"):
            pc.logging.info("Sandbox environments size: %.2fMB" % _dir_size(os.path.join(root, "sandbox")))
    return None


def daemon_set_telemetry(session, params):
    """Set a telemetry setting in the daemon's own configuration.

    The daemon-side counterpart of `pc system set telemetry ...`. It writes the
    configuration the daemon reads, which is a different file from the client's
    whenever the two are not the same machine.
    """
    pc = session.ensure_partcad()
    import partcad.actions.config as pc_actions_config

    key = params["key"]  # "type" | "env" | "sentryDsn"
    value = params["value"]
    process_name = {"type": "SysSetTelType", "env": "SysSetTelEnv", "sentryDsn": "SysSetTelDsn"}.get(key, "SysSet")
    with pc.logging.Process(process_name, "global"):
        yaml, config = pc_actions_config.system_config_get()
        if "telemetry" not in config:
            config["telemetry"] = {}
        config["telemetry"][key] = value
        if key == "type":
            if value == "none":
                pc.logging.info("Telemetry collection disabled")
            elif value == "sentry":
                pc.logging.info("Telemetry collection enabled with Sentry")
        elif key == "env":
            pc.logging.info("Telemetry environment set to %s" % value)
        elif key == "sentryDsn":
            pc.logging.info("Sentry DSN set to %s" % value)
        pc_actions_config.system_config_set(yaml, config)
    return None


def inspect_object(session, params):
    """Inspect an object: show it in the CAD viewer, or return a verbal summary."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    package = ctx.resolve_package_path(params.get("package"))
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name

    with pc.logging.Process("inspect", package):
        param_dict = {}
        for kv in params.get("params") or []:
            if "=" in kv:
                k, v = kv.split("=", 1)
                param_dict[k] = v

        object_name = params.get("object")
        if object_name is None:
            pc.logging.error("No object specified. Provide a part, assembly, sketch, interface, or scene to inspect.")
            return None

        package, object_name = pc.utils.resolve_resource_path(ctx.get_current_project_path(), object_name)
        path = "%s:%s" % (package, object_name)
        if params.get("assembly"):
            obj = ctx.get_assembly(path, params=param_dict)
        elif params.get("interface"):
            obj = ctx.get_interface(path)
        elif params.get("sketch"):
            obj = ctx.get_sketch(path, params=param_dict)
        else:
            obj = ctx.get_part(path, params=param_dict)

        if obj is None:
            pc.logging.error("Object %s is not found" % path)
            return None
        if params.get("verbal"):
            summary = obj.get_summary(package_obj)
            pc.logging.info("Summary: %s" % summary)
            return {"summary": summary}
        obj.show(ctx)
    return None


def version(session, params):
    """Return the PartCAD Python module version."""
    pc = session.ensure_partcad()
    return {"partcad": pc.__version__}


def healthcheck(session, params):
    """Run host health checks, streaming their output as log events."""
    pc = session.ensure_partcad()
    pc.healthcheck.tests.run_healthchecks(
        filters=params.get("filters"),
        fix=params.get("fix", False),
        dry_run=params.get("dry_run", False),
    )
    return {}


def _url_to_path(url: str) -> str:
    """Resolve a context URL to a local filesystem path.

    Only ``file://`` (and a bare path, treated as file://) is supported today —
    always the case for the CLI and the VS Code extension.
    TODO: extend to https:// and git URLs (fetch/clone into the sandbox, then
    load the resulting local directory).
    """
    parsed = urlparse(url)
    if parsed.scheme == "file":
        # url2pathname turns "/C:/x" back into "C:\x" on Windows and "/home/x"
        # into "/home/x" on POSIX, undoing Path.as_uri()'s encoding on both.
        path = url2pathname(parsed.path)
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            # A UNC authority ("file://host/share/..."); keep it.
            path = "//%s%s" % (parsed.netloc, path)
        return path
    # A bare path. A Windows path parses as a one-letter "scheme" ("C:\\pkg" ->
    # scheme 'c'), and no real URL scheme is a single character, so treat that as
    # a path too rather than rejecting it as an unsupported scheme.
    if parsed.scheme == "" or len(parsed.scheme) == 1:
        return url
    raise JsonRpcError(INVALID_CONFIG, "Unsupported context URL scheme: %s" % (parsed.scheme,))


def _caller_user_config(pc, params):
    """The configuration a context has to be built from, and its fingerprint.

    The daemon's own ``user_config`` is the wrong answer here. It was resolved
    from the environment that happened to start the daemon, and the daemon then
    stays warm for every later command, so it says nothing about how *this*
    command was invoked -- a ``pc --devel-index`` or ``PC_FORCE_UPDATE=1`` would
    be silently dropped the moment a daemon was already running. A client that
    knows its own configuration therefore sends a copy of it, and the context is
    built from that copy instead.

    The fingerprint is what the copy is compared against later. It is the sent
    data itself rather than a hash of it: the payload is small, comparing it is
    exact, and a hash would only add a way to be wrong.

    A client that sends nothing -- the VS Code extension, which configures the
    daemon once through its launch arguments -- keeps the daemon's own
    configuration, as before.
    """
    data = params.get("userConfig")
    if data is None:
        return None, pc.user_config
    return data, pc.UserConfig.from_dict(data)


def context_create(session, params):
    """Create (or reuse) a PartCAD context for a repository URL; return its id.

    The daemon persists contexts indefinitely, keyed by a deterministic id of
    the resolved root, so later commands reuse the warm context by passing the
    returned id back as ``context``. An unparseable ``partcad.yaml`` surfaces as
    the ``INVALID_CONFIG`` error, which the CLI renders as "Invalid configuration
    file".
    TODO: expire contexts (evict idle/old ones) so the registry does not grow
    without bound.
    """
    pc = session.ensure_partcad()
    # Path.as_uri(), not "file://" + path: the latter is not a valid URL for a
    # Windows path ("file://C:\\x" parses the drive as the authority), which
    # would build the context on the wrong root and give it an id that never
    # matches the one a client computes for the same directory.
    url = params.get("url") or Path(os.getcwd()).resolve().as_uri()
    path = _url_to_path(url)
    root = os.path.abspath(path)
    context_id = hashlib.sha256(root.encode("utf-8")).hexdigest()[:16]

    fingerprint, user_config = _caller_user_config(pc, params)

    # A warm context resolved its package graph -- which dependencies, from
    # which revisions, through which proxy -- against the configuration it was
    # built with. Reusing it for a caller configured differently would answer
    # this command from the other caller's graph, so it is rebuilt instead.
    # Nothing on disk is discarded: the git cache keys each revision separately,
    # so switching back and forth re-reads rather than re-clones.
    if context_id in session.contexts and session.context_user_configs.get(context_id) != fingerprint:
        session.contexts.pop(context_id, None)

    if context_id not in session.contexts:
        try:
            # Instantiate Context directly rather than via pc.init(): pc.init keeps
            # a module-level singleton keyed by path, so a second init of the same
            # path returns the first (now stale) context. The daemon serves many
            # independent, long-lived contexts and must read each one fresh from
            # disk -- especially after add/import mutate partcad.yaml.
            session.contexts[context_id] = pc.Context(path, user_config=user_config)
        except (yaml.parser.ParserError, yaml.scanner.ScannerError) as e:
            raise JsonRpcError(INVALID_CONFIG, "Invalid configuration file", data={"detail": str(e)}) from e
        session.context_user_configs[context_id] = fingerprint

    # Keep the most recently created context as the session default so the
    # extension's context-less operations continue to work.
    session.partcad_ctx = session.contexts[context_id]
    return {"context": context_id}


def ensure_loaded(session, params):
    """Load the workspace context once (idempotent), warming the daemon.

    The legacy single-context entry point (still used by the VS Code extension).
    New CLI commands use ``context.create`` + a ``context`` id instead.
    """
    pc = session.ensure_partcad()
    if session.partcad_ctx is None:
        session.partcad_ctx = pc.init(params.get("path") or os.getcwd(), user_config=pc.user_config)
    return {"loaded": session.partcad_ctx is not None}


def install(session, params):
    """Prepare the package the way 'npm install' prepares a Node.js one.

    Two halves. First the imported packages are downloaded, exactly as before.
    Then every sketch, part and assembly is asked for its cache key, which is
    what pulls in the rest: the key hashes the files an object is built from,
    so computing it downloads every 'fileFrom' URL, and getting there resolves
    each alias, enrich, compound and assembly link - loading the packages the
    objects really depend on, which are not always the ones 'partcad.yaml'
    names. Nothing is built; no CAD script runs.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    package = ctx.resolve_package_path(params.get("package") or ".")
    package_obj = ctx.get_project(package)
    if not package_obj:
        # A package the caller named by hand and that does not exist: a usage
        # error, so the CLI exits non-zero instead of reporting a clean install.
        raise JsonRpcError(USAGE_ERROR, "Package %s is not found" % package)
    package = package_obj.name

    # "this" (not the package name) is what this process has always been
    # labelled with, and what scripts watching for "DONE: Install: this:" match.
    with pc.logging.Process("Install", "this"):
        # Restore force_update afterwards: the daemon keeps this context warm,
        # so leaving it set would make every later command re-fetch everything.
        saved = ctx.user_config.force_update
        ctx.user_config.force_update = True
        try:
            all_packages = ctx.get_all_packages()
        finally:
            ctx.user_config.force_update = saved
        if ctx.stats_git_ops:
            session.emitter.info("Git operations: %s" % ctx.stats_git_ops)

        if params.get("recursive"):
            # A '/' has to follow the prefix, or '//sub' would also select the
            # unrelated sibling '//subwidget'.
            prefix = package if package.endswith("/") else package + "/"
            packages = [p["name"] for p in all_packages if p["name"] == package or p["name"].startswith(prefix)]
        else:
            packages = [package]
        stats = pc.actions.package.install(ctx, packages)

    session.emitter.info(
        "Installed %d sketches, %d parts and %d assemblies" % (stats["sketch"], stats["part"], stats["assembly"])
    )
    if stats["failed"]:
        session.emitter.error("Failed to install %d objects" % stats["failed"])
    if stats["failed_packages"]:
        session.emitter.error("Failed to install %d packages" % stats["failed_packages"])
    return stats


def update(session, params):
    """Force update all imported packages to their latest versions."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    # As in install(): scope force_update to this call so the warm context does
    # not stay in force-update mode for every subsequent command.
    saved = ctx.user_config.force_update
    ctx.user_config.force_update = True
    try:
        packages = list(ctx.get_all_packages())
    finally:
        ctx.user_config.force_update = saved
    if ctx.stats_git_ops:
        session.emitter.info("Git operations: %s" % ctx.stats_git_ops)
    session.emitter.info("Successfully updated %d packages" % len(packages))
    return {"count": len(packages)}


# ---- lifecycle -------------------------------------------------------------


def activate(session, params):
    """Load PartCAD, verify version, run health checks, and signal readiness."""
    try:
        session.load_partcad()
        if session.partcad.__version__ not in SpecifierSet(">=0.8.16"):
            session.emitter.error("Failed to activate PartCAD: PartCAD Python module is not up-to-date.")
            session.emitter.signal(events.ACTIVATE_FAILED)
            return None
        session.partcad.healthcheck.tests.run_healthchecks()
        session.emitter.signal(events.LOADED)
    except Exception as e:  # pylint: disable=broad-except
        session.emitter.error(
            "Failed to activate PartCAD: %s.\nFollow instructions in the PartCAD's Explorer view." % e
        )
        session.emitter.signal(events.ACTIVATE_FAILED)
    return None


def init(session, params):
    """Create a new package and load it."""
    if session.partcad is None:
        session.emitter.signal(events.PACKAGE_LOAD_FAILED)
        session.emitter.error("Create a package while PartCAD is not loaded")
        return None
    try:
        path = params.get("path") or os.getcwd()
        session.package_path = path
        if os.path.isdir(path):
            path = os.path.join(path, "partcad.yaml")
        if session.partcad.create_package(path):
            # The same "Render" command `pc init` adds, for the same reason: the
            # IDE shows it in "Run and Debug" as soon as the package exists.
            session.partcad.add_render_configuration(os.path.dirname(os.path.abspath(path)))
            session.partcad_ctx = session.partcad.init(path)
            session.emitter.emit(
                events.PACKAGE_LOADED,
                {"configPath": _root_config_path(session.partcad_ctx), "root": session.partcad_ctx.name},
            )
            _load_package_contents(session, session.partcad_ctx.name)
        else:
            session.emitter.signal(events.PACKAGE_LOAD_FAILED)
            session.emitter.error("Failed to create package")
    except session.partcad.exception.NeedsUpdateException:
        session.emitter.signal(events.NEEDS_UPDATE)
    except Exception as e:  # pylint: disable=broad-except
        session.emitter.signal(events.PACKAGE_LOAD_FAILED)
        session.emitter.error("Failed to create package: %s" % e)
    return None


def package_load(session, params):
    """Load an existing package."""
    if session.partcad is None:
        session.emitter.signal(events.PACKAGE_LOAD_FAILED)
        session.emitter.error("Load a package while PartCAD is not loaded")
        return None
    try:
        path = params.get("path") or os.getcwd()
        session.package_path = path
        session.partcad_ctx = session.partcad.init(path)
        session.emitter.emit(
            events.PACKAGE_LOADED,
            {"configPath": _root_config_path(session.partcad_ctx), "root": session.partcad_ctx.name},
        )
        _load_package_contents(session, session.partcad_ctx.name)
    except session.partcad.exception.NeedsUpdateException:
        session.emitter.signal(events.NEEDS_UPDATE)
    except Exception as e:  # pylint: disable=broad-except
        # Reported unconditionally: the guard this replaces suppressed the
        # message in exactly the cases that need it.
        session.emitter.signal(events.PACKAGE_LOAD_FAILED)
        session.emitter.error("Failed to load package: %s" % e)
    return None


def package_refresh(session, params):
    """Force-refresh all packages and reload the contents."""
    if session.partcad is None:
        session.emitter.error("Refreshing packages while PartCAD is not loaded")
        return None
    try:
        session.emitter.info("Beginning to refresh the packages...")
        with session.partcad.logging.Process("Refresh", "this"):
            saved = session.partcad.user_config.force_update
            session.partcad.user_config.force_update = True
            session.partcad_ctx.get_all_packages()
            session.partcad.user_config.force_update = saved
        _load_package_contents(session)
        session.emitter.info("Completed refreshing the packages")
    except session.partcad.exception.NeedsUpdateException:
        session.emitter.signal(events.NEEDS_UPDATE)
    except Exception as e:  # pylint: disable=broad-except
        session.emitter.error("Failed to refresh the package: %s" % e)
    return None


def list_all(session, params):
    """Load and report the contents (packages/sketches/interfaces/parts/assemblies)."""
    if session.partcad is None:
        session.emitter.error("Loading the package content while PartCAD is not loaded")
        return None
    try:
        _load_package_contents(session, params.get("name", "//"))
    except session.partcad.exception.NeedsUpdateException:
        session.emitter.signal(events.NEEDS_UPDATE)
    except Exception as e:  # pylint: disable=broad-except
        session.emitter.error("Failed to load package contents: %s" % e)
    return None


# The four object kinds `pc list <kind>` renders identically (name + description
# table, optional package column when recursive). One operation serves all four;
# the CLI passes the kind. Output is emitted verbatim through PartCAD's logger so
# it renders exactly as the old in-process command did.
_LIST_LABELS = {
    "parts": "PartCAD parts",
    "sketches": "PartCAD sketches",
    "assemblies": "PartCAD assemblies",
    "interfaces": "PartCAD interfaces",
}


def list_objects(session, params):
    """List a package's parts, sketches, assemblies, or interfaces."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    kind = params.get("kind", "parts")
    recursive = params.get("recursive", False)

    package = ctx.resolve_package_path(params.get("package", "."))
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name  # '//' may resolve to a differently-named package

    with pc.logging.Process("List" + kind.capitalize(), package):
        count = 0
        if recursive:
            # `list interfaces` walks every package; the others only those with content.
            has_stuff = kind != "interfaces"
            packages = [p["name"] for p in ctx.get_all_packages(parent_name=package, has_stuff=has_stuff)]
        else:
            packages = [package]

        output = _LIST_LABELS.get(kind, "PartCAD objects") + ":\n"
        for project_name in packages:
            project = ctx.projects[project_name]
            for name, obj in getattr(project, kind).items():
                line = "\t"
                if recursive:
                    line += "%s" % project_name + " " + " " * (35 - len(project_name))
                line += "%s" % name + " " + " " * (35 - len(name))
                desc = obj.desc if obj.desc is not None else ""
                desc = desc.replace("\n", "\n" + " " * (84 if recursive else 44))
                line += "%s" % desc
                output += line + "\n"
                count += 1

        if count > 0:
            output += "Total: %d\n" % count
        else:
            output += "\t<none>\n"
        pc.logging.info(output)
    return None


def list_packages(session, params):
    """List imported packages that have at least one sketch, part, or assembly."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    recursive = params.get("recursive", False)
    package = ctx.resolve_package_path(params.get("package", "."))
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name

    with pc.logging.Process("ListPackages", package):
        pkg_count = 0
        if recursive:
            packages = [p["name"] for p in ctx.get_all_packages(parent_name=package, has_stuff=True)]
        else:
            packages = [package]

        output = "PartCAD packages:\n"
        for project_name in packages:
            project = ctx.projects[project_name]
            line = "\t%s" % project_name
            padding_size = 60 - len(project_name)
            if padding_size < 4:
                padding_size = 4
            line += " " * padding_size
            desc = project.desc if project.desc is not None else ""
            if hasattr(project, "url"):
                desc += "\n%s" % project.url
            desc = desc.replace("\n", "\n" + " " * 68)
            line += "%s" % desc
            output += line + "\n"
            pkg_count += 1

        if pkg_count < 1:
            output += "\t<none>\n"
        pc.logging.info(output)
    return None


def list_providers(session, params):
    """List available providers."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    recursive = params.get("recursive", False)
    package = ctx.resolve_package_path(params.get("package", "."))
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name

    with pc.logging.Process("ListProviders", package):
        provider_kinds = 0
        if recursive:
            projects = sorted(p["name"] for p in ctx.get_all_packages(package if package != "." else None))
        else:
            projects = [package]

        output = "PartCAD providers:\n"
        for project_name in projects:
            if not recursive and package != project_name:
                continue
            if (
                recursive
                and package != "//"
                and project_name != package
                and not project_name.startswith("%s/" % package)
            ):
                continue
            project = ctx.projects[project_name]
            for provider_name, provider in project.providers.items():
                line = "\t"
                if recursive:
                    line += "%s" % project_name + " " + " " * (35 - len(project_name))
                line += "%s" % provider_name + " " + " " * (35 - len(provider_name))
                desc = provider.desc if provider.desc is not None else ""
                desc = desc.replace("\n", "\n" + " " * (80 if recursive else 44))
                line += "%s" % desc
                output += line + "\n"
                provider_kinds += 1

        if provider_kinds > 0:
            output += "Total: %d\n" % provider_kinds
        else:
            output += "\t<none>\n"
        pc.logging.info(output)
    return None


def list_mates(session, params):
    """List available mating interfaces."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    recursive = params.get("recursive", False)
    package = ctx.resolve_package_path(params.get("package", "."))
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name

    with pc.logging.Process("ListMates", package):
        mating_kinds = 0
        if recursive:
            packages = [p["name"] for p in ctx.get_all_packages(parent_name=package)]
        else:
            packages = [package]

        # Instantiate interfaces so the mating data is finalized.
        for package_name in packages:
            prj = ctx.projects[package_name]
            for interface_name in prj.interfaces:
                prj.get_interface(interface_name).instantiate()

        output = "PartCAD mating interfaces:\n"
        for source_interface_name in ctx.mates:
            source_package_name = source_interface_name.split(":")[0]
            display_source = (
                source_interface_name if source_package_name != package else source_interface_name.split(":")[1]
            )
            for target_interface_name in ctx.mates[source_interface_name]:
                target_package_name = target_interface_name.split(":")[0]
                display_target = (
                    target_interface_name if target_package_name != package else target_interface_name.split(":")[1]
                )
                mating = ctx.mates[source_interface_name][target_interface_name]
                if (
                    recursive
                    and not source_package_name.startswith(package)
                    and not target_package_name.startswith(package)
                ):
                    continue
                if not recursive and source_package_name != package and target_package_name != package:
                    continue
                line = "\t"
                line += "%s" % display_source + " " + " " * (35 - len(display_source))
                line += "%s" % display_target + " " + " " * (35 - len(display_target))
                desc = mating.desc if mating.desc is not None else ""
                desc = desc.replace("\n", "\n\t" + " " * 72)
                line += "%s" % desc
                output += line + "\n"
                mating_kinds += 1

        if mating_kinds > 0:
            output += "Total: %d mating interfaces\n" % mating_kinds
        else:
            output += "\t<none>\n"
        pc.logging.info(output)
    return None


def bom(session, params):
    """Print the bill of materials of an assembly.

    Returns the line items so the CLI can render them as JSON; the human-readable
    table is emitted here, through PartCAD logging, the way `pc list` renders its
    own. ``stop_at_purchasable`` keeps sub-assemblies that can be bought whole
    from being expanded into their contents.
    """
    import asyncio

    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad

    resolved = _resolve_object(ctx, pc, params)
    if resolved is None:
        return None
    package, object_name = resolved
    path = _qualified(package, object_name)

    param_dict = {}
    for kv in params.get("params") or []:
        if "=" in kv:
            k, v = kv.split("=", 1)
            param_dict[k] = v

    with pc.logging.Process("BoM", package, object_name):
        assembly = ctx.get_assembly(path, params=param_dict)
        if assembly is None:
            pc.logging.error("Assembly %s is not found" % path)
            return None

        bom_items = asyncio.run(
            assembly.get_bom_detailed_async(ctx, stop_at_purchasable=bool(params.get("stop_at_purchasable")))
        )

        items = [{"name": name, **entry} for name, entry in sorted(bom_items.items())]
        result = {
            "assembly": path,
            "items": items,
            "total": sum(item["count"] for item in items),
        }

        if not params.get("json"):
            pc.logging.info(_bom_output(result))
    return result


def _bom_output(result: dict) -> str:
    """The human-readable rendering of a BoM: one line item per line.

    The columns are sized from the content, not fixed the way `pc list` sizes
    its own: every name here carries the package it comes from, so the names are
    long and their length varies a lot from one BoM to the next.
    """
    items = result["items"]
    output = "Bill of materials of %s:\n" % result["assembly"]
    if not items:
        return output + "\t<none>\n"

    rows = []
    for item in items:
        # What to order, for the items that say so: buying one needs the vendor
        # and the SKU, not the name PartCAD knows it by.
        if item.get("vendor") and item.get("sku"):
            source = "%s %s" % (item["vendor"], item["sku"])
        else:
            source = ""
        rows.append((item["name"], str(item["count"]), source, item.get("desc") or ""))

    name_width = max(len(row[0]) for row in rows)
    count_width = max(len(row[1]) for row in rows)
    source_width = max(len(row[2]) for row in rows)

    # Where a folded description continues, counting the leading tab as one.
    indent = 1 + name_width + 2 + count_width + 2 + (source_width + 2 if source_width else 0)
    for name, count, source, desc in rows:
        line = "\t%s  %s" % (name.ljust(name_width), count.rjust(count_width))
        if source_width:
            line += "  %s" % source.ljust(source_width)
        line += "  " + desc.replace("\n", "\n" + " " * indent)
        output += line.rstrip() + "\n"
    output += "Total: %d\n" % result["total"]
    return output


def assembly_guide(session, params):
    """Return the assembly instruction book of an assembly as plain data.

    The very document ``pc render -t html|pdf`` writes to a file (see
    ``Project.render_assembly_guide_async``), handed over as the renderer-
    independent model in ``partcad.document`` with every illustration inlined as
    a data URI. That is for a reader with no file system in reach: the IDE's
    viewer is a webview on the other side of this connection, and the pictures of
    an instruction book live in a temporary directory that is deleted as soon as
    the document has been built.
    """
    import asyncio

    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad

    resolved = _resolve_object(ctx, pc, params)
    if resolved is None:
        return None
    package, object_name = resolved

    from partcad.exception import AssemblyDocumentError

    project = ctx.get_project(package)
    if project is None:
        pc.logging.error("Package %s is not found" % package)
        return None

    with pc.logging.Process("Guide", package, object_name):
        try:
            document = asyncio.run(
                project.assembly_guide_data_async(
                    object_name,
                    ignore_manufacturability=bool(params.get("ignore_manufacturability")),
                )
            )
        except AssemblyDocumentError as e:
            # Asking for the instructions of something that has no assembly
            # steps, or that is not meant to be built: what the user asked for,
            # not a failure of the machinery.
            raise JsonRpcError(USAGE_ERROR, str(e)) from e
        if document is None:
            pc.logging.error("Assembly %s:%s is not found" % (package, object_name))
            return None

    return {"assembly": _qualified(package, object_name), "document": document}


def supply_quote(session, params):
    """Where to buy what an object is made of, and for how much.

    One line item per thing to order -- a part, or a sub-assembly that is sold
    assembled, exactly as ``pc supply quote`` fills its cart -- and, under each,
    every supplier that has it, cheapest first. An object that is itself a part
    is one line item with its own suppliers under it.

    Each option is quoted from a cart holding that one line item, rather than
    from one cart per supplier: a cart of the whole assembly comes back as a
    single price for all of it, which cannot say what any one part costs.
    """
    import asyncio

    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad

    resolved = _resolve_object(ctx, pc, params)
    if resolved is None:
        return None
    package, object_name = resolved
    path = _qualified(package, object_name)

    with pc.logging.Process("Supply", package, object_name):
        result = asyncio.run(
            _supply_quote_async(
                pc,
                ctx,
                path,
                qos=params.get("qos") or None,
                recursive=bool(params.get("recursive")),
            )
        )
    result["object"] = path
    return result


async def _supply_quote_async(pc, ctx, path, qos, recursive):
    """The body of 'supply_quote', once the request has been made sense of."""
    from partcad.plugin_provider_data_cart import ProviderCart, resolve_cart_object

    cart = ProviderCart(qos=qos)
    try:
        await cart.add_object(ctx, path, recursive=recursive)
    except Exception as e:
        raise JsonRpcError(USAGE_ERROR, "Nothing to supply for %s: %s" % (path, e)) from e

    items = []
    for name, cart_item in sorted(cart.parts.items()):
        options = []
        for supplier_name in await _item_suppliers(pc, ctx, cart_item, cart):
            option = await _supply_option(pc, ctx, cart_item, supplier_name, qos)
            if option is not None:
                options.append(option)
        # Cheapest first: what this is read for is which of them to order from.
        # A supplier that answered with no price at all sorts last rather than
        # winning by comparing as zero.
        options.sort(key=lambda option: (option.get("price") is None, option.get("price") or 0.0))

        # What the line item is, for the reader: a cart item carries the store
        # data and nothing that says what the thing is.
        shape = resolve_cart_object(ctx, name)
        items.append(
            {
                "name": name,
                "kind": getattr(shape, "kind", None),
                "desc": getattr(shape, "desc", None),
                "count": cart_item.count,
                "vendor": cart_item.vendor,
                "sku": cart_item.sku,
                "count_per_sku": cart_item.count_per_sku,
                "suppliers": options,
            }
        )

    return {"items": items, "totals": _supply_totals(items)}


async def _item_suppliers(pc, ctx, cart_item, cart):
    """The suppliers of one line item, without complaining when there are none.

    ``Context.find_part_suppliers()`` reports "no suppliers" as an error, which
    is right for ``pc supply find`` -- it was asked to find one -- but not here:
    this is asked about whatever the viewer happens to be showing, and a package
    that declares no supplier is the ordinary case rather than a failure. In the
    IDE an error is a modal popup, one per part.
    """
    project_name, _ = pc.utils.resolve_resource_path(ctx.current_project_path, cart_item.name)
    project = ctx.get_project(project_name)
    if project is None or not project.get_suppliers():
        return []
    return await ctx.find_part_suppliers(cart_item, cart)


async def _supply_option(pc, ctx, cart_item, provider_name, qos):
    """What one supplier asks for one line item."""
    from partcad.plugin_provider_data_cart import ProviderCart
    from partcad.plugin_request_provider_quote import ProviderRequestQuote

    provider = ctx.get_provider(provider_name)
    if provider is None:
        return None

    cart = ProviderCart(qos=qos)
    item = cart.add_item(cart_item)
    option = {
        "name": provider_name,
        "desc": getattr(provider, "desc", None) or None,
        "url": getattr(provider, "url", None),
        "currency": _provider_currency(provider),
    }

    try:
        # Loading is what makes it a supplier cart rather than a plain one: a
        # manufacturer needs the CAD model in a format it accepts before it can
        # say what making the part would cost.
        await provider.load(item)
        request = ProviderRequestQuote(cart)
        request.set_result(await provider.query_quote(request))
    except Exception as e:
        # One supplier that will not quote is not a failure of the request: the
        # others still have prices, and why this one did not is worth showing.
        pc.logging.debug("No quote from %s for %s: %s" % (provider_name, cart_item.name, e))
        option["error"] = str(e)
        return option

    result = request.result or {}
    option.update(
        {
            "price": _as_price(result.get("price")),
            "cartId": result.get("cartId"),
            "expire": result.get("expire"),
            "etaMin": result.get("etaMin"),
            "etaMax": result.get("etaMax"),
            "qos": result.get("qos"),
        }
    )
    return option


def _as_price(value):
    """A quoted price as a number, or None when the provider did not give one.

    A quote is whatever a provider's own script put in it, and everything
    downstream of here treats the price as a number: the options are sorted by
    it and the cheapest of each are added up. A string where a number belongs
    would fail the whole request rather than the one supplier that sent it, so it
    is read as "no price" instead.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    # A quote of NaN or infinity sorts and sums as nonsense.
    return price if math.isfinite(price) else None


def _provider_currency(provider):
    """What a provider quotes in, when its configuration says.

    A quote carries 'price' as a bare number, so the unit has to come from
    somewhere else; a store declares it as a parameter (see
    ``examples/provider_store``).
    """
    config = getattr(provider, "config", None) or {}
    currency = (config.get("parameters") or {}).get("currency")
    if isinstance(currency, dict):
        currency = currency.get("default")
    if not isinstance(currency, str):
        currency = (config.get("with") or {}).get("currency")
    return currency if isinstance(currency, str) else None


def _supply_totals(items):
    """What ordering every line item from its cheapest supplier would come to.

    Kept per currency rather than added up into one number: two suppliers that
    quote in different currencies cannot be summed without an exchange rate, and
    PartCAD has none.
    """
    totals = {}
    for item in items:
        best = item["suppliers"][0] if item["suppliers"] else None
        if best is None or best.get("price") is None:
            continue
        currency = best.get("currency") or ""
        totals[currency] = totals.get(currency, 0.0) + best["price"]
    return [{"currency": currency or None, "price": price} for currency, price in sorted(totals.items())]


def search_objects(session, params):
    """Search parts/sketches/assemblies/interfaces/packages by keyword."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    kind = params.get("kind", "parts")
    recursive = params.get("recursive", False)
    keyword = params.get("keyword", "")
    package = ctx.resolve_package_path(params.get("package", "//"))

    from partcad.actions.package import search_packages
    from partcad.actions.shape import (
        search_assemblies,
        search_interfaces,
        search_parts,
        search_sketches,
    )

    search_fns = {
        "parts": search_parts,
        "sketches": search_sketches,
        "assemblies": search_assemblies,
        "interfaces": search_interfaces,
        "packages": search_packages,
    }
    search_fn = search_fns.get(kind, search_parts)

    count = 0
    output = "PartCAD %s with '%s' keyword:\n" % (kind, keyword)
    with pc.logging.Process("Search " + kind.capitalize(), package):
        for obj in search_fn(ctx, package, recursive, keyword):
            if kind == "packages":
                line = "\t%s" % obj.name
                padding_size = 60 - len(obj.name)
                if padding_size < 4:
                    padding_size = 4
                line += " " * padding_size
                desc = obj.desc if obj.desc is not None else ""
                if obj.config_obj.get("url"):
                    desc += "\n%s" % obj.config_obj["url"]
                desc = desc.replace("\n", "\n" + " " * 68)
                line += "%s" % desc
            else:
                # Interfaces expose their package as `.project`; parts, sketches
                # and assemblies carry a flat `.project_name` (matches the
                # per-command CLI behavior on devel).
                project_name = obj.project.name if kind == "interfaces" else obj.project_name
                line = "\t" + "%s %s" % (project_name, obj.name)
                line += " " + " " * (84 - len(line))
                desc = obj.desc if obj.desc is not None else ""
                desc = desc.replace("\n", "\n\t" + " " * (len(line) - 1))
                line += "%s" % desc
            output += line + "\n"
            count += 1

        if count > 0:
            output += "Matches: %d\n" % count
        else:
            output += "\t<none>\n"
    pc.logging.info(output)
    return None


def _validate_output_format(pc, ctx, fmt, packages):
    """Reject a file type nothing implements, instead of quietly writing nothing.

    The set is not fixed: on top of what `//builtin/export` and `//builtin/render`
    implement, a package may declare a file type of its own in its `export:` or
    `render:` section, and that has to be nameable on the command line.
    """
    if fmt is None:
        return
    known = set(pc.output.all_formats(ctx)) | pc.output.NON_WRAPPER_FORMATS
    for package in packages:
        package_obj = ctx.get_project(package)
        if package_obj is None:
            continue
        for section in pc.output.SECTIONS:
            known.update(pc.output.format_names(package_obj.config_obj.get(section)))
    if fmt not in known:
        raise JsonRpcError(
            USAGE_ERROR,
            "Unknown output file type '%s'. Known types: %s" % (fmt, ", ".join(sorted(known))),
        )


def render_objects(session, params):
    """Render/export parts, assemblies, sketches, or interfaces to files.

    Backs both `pc export` (3D formats) and `pc render` (2D projections); the CLI
    passes the ``format`` and the ``label`` ("Export"/"Render"). ``output_dir``,
    when given, is resolved to an absolute path by the CLI so it lands in the
    user's working directory (the daemon runs elsewhere). ``options_package``
    names a further package whose ``export:``/``render:`` sections are read on
    top of the built-in ones, which is how a custom implementation declared in
    one package is used against the objects of another.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    package = ctx.resolve_package_path(params.get("package") or ".")
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name

    fmt = params.get("format")
    output_dir = params.get("output_dir")
    object_name = params.get("object")
    ignore_manufacturability = params.get("ignore_manufacturability", False)
    options_package = params.get("options_package")
    if options_package:
        options_package = ctx.resolve_package_path(options_package)
        if ctx.get_project(options_package) is None:
            raise JsonRpcError(USAGE_ERROR, "Options package %s is not found" % options_package)

    from partcad.exception import AssemblyDocumentError

    with pc.logging.Process(params.get("label", "Render"), package):
        ctx.option_create_dirs = params.get("create_dirs", False)
        try:
            _render_objects(
                pc,
                ctx,
                params,
                package,
                fmt,
                output_dir,
                object_name,
                options_package,
                ignore_manufacturability,
            )
        except AssemblyDocumentError as e:
            # Asking for an assembly instruction book of something that has no
            # assembly steps, or that is not meant to be built: what the user
            # asked for, not a failure of the machinery.
            raise JsonRpcError(USAGE_ERROR, str(e)) from e
    return None


def _render_objects(
    pc,
    ctx,
    params,
    package,
    fmt,
    output_dir,
    object_name,
    options_package,
    ignore_manufacturability,
):
    """The body of 'render_objects', once the request has been made sense of."""
    import asyncio

    if params.get("recursive"):
        packages = [p["name"] for p in ctx.get_all_packages(parent_name=package, has_stuff=True)]
    else:
        packages = [package]

    # An object named as '<package>:<name>' is produced by that package, not
    # by the one '--package' selected, so its file types count as known too.
    validated_packages = list(packages)
    if object_name is not None:
        validated_packages += [pc.utils.resolve_resource_path(p, object_name)[0] for p in packages]
    if options_package:
        validated_packages.append(options_package)
    _validate_output_format(pc, ctx, fmt, validated_packages)

    asyncio.run(
        _render_packages_async(
            pc,
            ctx,
            params,
            packages,
            fmt,
            output_dir,
            object_name,
            options_package,
            ignore_manufacturability,
        )
    )


async def _render_packages_async(
    pc,
    ctx,
    params,
    packages,
    fmt,
    output_dir,
    object_name,
    options_package,
    ignore_manufacturability,
):
    """Render the given packages, several at a time.

    A package used to be rendered by its own 'asyncio.run()' after the previous
    one had finished, so a recursive render cost the sum of its packages even
    though nothing relates one package's files to another's. They are gathered
    here instead, the way a recursive test and a recursive lint already gather
    theirs.

    Bounded, because a package admits every one of its shapes and every file
    type of each at once: what keeps the machine busy is the sandbox process
    budget (see partcad.sandbox_lock), and enough packages to keep that budget
    full is all the concurrency there is any use for.

    Nothing is cancelled when one package fails. A render writes files, and a
    package interrupted half way through writing them is worse than one that
    finishes and reports; the first failure is raised once they are all done,
    which is what the caller would have seen anyway.
    """
    import asyncio

    from partcad.sandbox_lock import process_slots

    # The packages PartCAD ships inside itself are loaded on demand, by the
    # first thing that asks what file types exist (see
    # Context._get_builtin_project). Ask once here, before anything runs, so
    # that several packages arriving at that question together do not each
    # import them.
    pc.output.all_formats(ctx)

    at_once = asyncio.Semaphore(max(1, process_slots.count))

    async def render_package(package):
        object_in_package = object_name
        if object_in_package is not None:
            package, object_in_package = pc.utils.resolve_resource_path(package, object_in_package)

        async with at_once:
            if object_in_package is None:
                await ctx.render_async(
                    project_path=package,
                    format=fmt,
                    output_dir=output_dir,
                    options_package=options_package,
                    ignore_manufacturability=ignore_manufacturability,
                )
            else:
                sketches, interfaces, parts, assemblies = [], [], [], []
                if params.get("sketch"):
                    sketches.append(object_in_package)
                elif params.get("interface"):
                    interfaces.append(object_in_package)
                elif params.get("assembly"):
                    assemblies.append(object_in_package)
                else:
                    parts.append(object_in_package)
                prj = ctx.get_project(package)
                await prj.render_async(
                    sketches=sketches,
                    interfaces=interfaces,
                    parts=parts,
                    assemblies=assemblies,
                    format=fmt,
                    output_dir=output_dir,
                    options_package=options_package,
                    ignore_manufacturability=ignore_manufacturability,
                )

    results = await asyncio.gather(*[render_package(package) for package in packages], return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result


def convert_object(session, params):
    """Convert a part or sketch to another format and update its type."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    kind = params.get("kind", "part")
    object_name = params["object_name"]
    target_format = params.get("target_format")
    output_dir = params.get("output_dir")
    dry_run = params.get("dry_run", False)

    if kind in ("part", "assembly"):
        package = ctx.resolve_package_path(params.get("package") or ".")
    else:
        package = params.get("package") if params.get("package") is not None else "."
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        raise JsonRpcError(USAGE_ERROR, "Failed to retrieve the project.")

    from partcad.actions.part import convert_part_action
    from partcad.actions.sketch import convert_sketch_action

    if kind == "assembly":
        from partcad.actions.assembly import convert_assembly_action

        action = convert_assembly_action
        starting_msg = "Starting assembly conversion: '%s' -> '%s', dry_run=%s" % (
            object_name,
            target_format,
            dry_run,
        )
        done_msg = "Assembly conversion of '%s' completed." % object_name
    elif kind == "part":
        action = convert_part_action
        starting_msg = "Starting conversion: '%s' -> '%s', dry_run=%s" % (object_name, target_format, dry_run)
        done_msg = "Conversion of '%s' completed." % object_name
    else:
        action = convert_sketch_action
        starting_msg = "Starting sketch conversion: '%s' -> '%s', dry_run=%s" % (object_name, target_format, dry_run)
        done_msg = "Sketch conversion of '%s' completed." % object_name

    pc.logging.info(starting_msg)
    try:
        action(package_obj, object_name, target_format, output_dir=output_dir, dry_run=dry_run)
    except ValueError as e:
        raise JsonRpcError(USAGE_ERROR, str(e))
    pc.logging.info(done_msg)
    return None


def _load_package_contents(session, name="//"):
    ctx = session.partcad_ctx
    with session.partcad.logging.Process("Load", name):
        project = ctx.get_project(name)
        if project is None or project.broken:
            # The legacy LSP server guarded this message with
            # `project is not None and not project.broken`, which is
            # unreachable inside this branch -- the failure signal fired with
            # no explanation. Report the package that failed to load.
            session.emitter.error("Failed to load the package: %s" % name)
            session.emitter.signal(events.PACKAGE_LOAD_FAILED)
            return

        def pkg_obj(pkg):
            return {
                **pkg.config_obj,
                "item_path": pkg.config_path if hasattr(pkg, "config_path") else None,
                "item_dir": pkg.config_dir if hasattr(pkg, "config_dir") else pkg.path,
            }

        # Per child, so one unloadable sub-package does not cost the user the
        # whole tree. ``get_project()`` returns None for a package that could
        # not be loaded, which ``pkg_obj()`` would then fail on.
        packages = []
        for child_name in project.get_child_project_names():
            try:
                child = ctx.get_project(child_name)
                if child is None:
                    raise Exception("the package could not be loaded")
                packages.append(pkg_obj(child))
            except session.partcad.exception.NeedsUpdateException:
                # Not per-package: this says PartCAD itself is too old, and the
                # caller turns it into the "update PartCAD" prompt.
                raise
            except Exception as e:  # pylint: disable=broad-except
                session.emitter.warning("Skipping the package '%s': %s" % (child_name, e))

    def item_objs(objects, with_path=True):
        """Describe each object for the client, skipping any that cannot be described.

        Per object, so that one that misbehaves costs the user that row rather
        than the whole listing.
        """
        described = []
        for object_name, obj in list(objects.items()):
            try:
                path = getattr(obj, "path", None) if with_path else None
                described.append(
                    {**obj.config, "item_path": (os.path.join(project.config_dir, path) if path else None)}
                )
            except Exception as e:  # pylint: disable=broad-except
                session.emitter.warning("Skipping '%s:%s': %s" % (name, object_name, e))
        return described

    sketches = item_objs(project.sketches)
    interfaces = item_objs(project.interfaces, with_path=False)
    parts = item_objs(project.parts)
    assemblies = item_objs(project.assemblies)

    # Objects the package declares but PartCAD could not create - most often one
    # written against a PartCAD that still had a feature since retired (the
    # 'ai-*' part types the public index still carries). They are reported
    # alongside the working ones because a package that lists nothing is
    # indistinguishable from an empty one and gives the user nothing to act on.
    broken = [
        {"kind": kind, "name": object_name, "reason": reason}
        for kind, objects in getattr(project, "broken_objects", {}).items()
        for object_name, reason in objects.items()
    ]
    if broken:
        session.emitter.warning(
            "%d object(s) in '%s' could not be loaded. See the PartCAD Explorer for which, and why."
            % (len(broken), name)
        )

    session.emitter.emit(
        events.ITEMS,
        {
            "name": name,
            "packages": packages,
            "sketches": sketches,
            "interfaces": interfaces,
            "parts": parts,
            "assemblies": assemblies,
            "broken": broken,
        },
    )
    info(session, {})
