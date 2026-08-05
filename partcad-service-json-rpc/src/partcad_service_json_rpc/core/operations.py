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
import os
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
        path = ctx.config_path
    _inspect_by_path(session, path)
    return None


def _inspect_by_path(session, path):
    ctx = session.partcad_ctx
    with session.partcad.logging.Process("InspectFile", path):
        for prj_name, prj in ctx.projects.items():
            for name, assy in prj.assemblies.items():
                if hasattr(assy, "orig_name") and assy.name != assy.orig_name:
                    continue
                if assy.path is not None and os.path.exists(assy.path) and os.path.samefile(assy.path, path):
                    for paramed in list(filter(lambda n: n.startswith(name), prj.assemblies.keys())):
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
                    for paramed in list(filter(lambda n: n.startswith(name), prj.parts.keys())):
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
                    for paramed in list(filter(lambda n: n.startswith(name + ":"), prj.sketches.keys())):
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
    sandboxed wrappers: importing an assembly drives ``wrapper_import_assy`` in
    a Python runtime, and ``--target-format`` converts through the same
    machinery. Those runtimes belong to the daemon's environment and need not
    exist on the client side at all.
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
    path = ctx.config_path
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
                shape = prj.get_part(obj)
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


def system_reset(session, params):
    """Reset PartCAD's internal state (cached repos, sandboxes, filesystem cache).

    Because the daemon holds warm contexts that reference these directories, the
    context registry is cleared too so later commands rebuild from clean state.
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
    session.partcad_ctx = None
    return None


def system_status(session, params):
    """Report PartCAD's version and internal storage usage.

    Output matches the in-process ``pc system status`` (human-readable MB sizes
    and the "<X> cache size:" labels the behave scenarios assert on).
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


def system_set_telemetry(session, params):
    """Set a telemetry configuration value (type/env/sentryDsn) persistently.

    Messages and per-key Process names mirror the in-process CLI commands the
    behave scenarios assert on.
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


def prompt_respond(session, params):
    """Deliver a response to a pending interactive prompt."""
    session.provide_prompt_response(params["response"] + os.linesep)
    return None


# ---- host / info -----------------------------------------------------------


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
    if parsed.scheme == "":
        return url
    raise JsonRpcError(INVALID_CONFIG, "Unsupported context URL scheme: %s" % (parsed.scheme,))


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
    url = params.get("url") or ("file://" + os.getcwd())
    path = _url_to_path(url)
    root = os.path.abspath(path)
    context_id = hashlib.sha256(root.encode("utf-8")).hexdigest()[:16]

    if context_id not in session.contexts:
        try:
            # Instantiate Context directly rather than via pc.init(): pc.init keeps
            # a module-level singleton keyed by path, so a second init of the same
            # path returns the first (now stale) context. The daemon serves many
            # independent, long-lived contexts and must read each one fresh from
            # disk -- especially after add/import mutate partcad.yaml.
            session.contexts[context_id] = pc.Context(path, user_config=pc.user_config)
        except (yaml.parser.ParserError, yaml.scanner.ScannerError) as e:
            raise JsonRpcError(INVALID_CONFIG, "Invalid configuration file", data={"detail": str(e)}) from e

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
    """Download and set up all imported packages."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    with session.partcad.logging.Process("Install", "this"):
        # Restore force_update afterwards: the daemon keeps this context warm,
        # so leaving it set would make every later command re-fetch everything.
        saved = ctx.user_config.force_update
        ctx.user_config.force_update = True
        try:
            ctx.get_all_packages()
        finally:
            ctx.user_config.force_update = saved
        if ctx.stats_git_ops:
            session.emitter.info("Git operations: %s" % ctx.stats_git_ops)
    return {}


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
        if session.partcad.__version__ not in SpecifierSet(">=0.7.153"):
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
            session.partcad_ctx = session.partcad.init(path)
            if session.partcad_ctx and not getattr(session.partcad_ctx, "broken", False):
                session.emitter.emit(
                    events.PACKAGE_LOADED,
                    {"configPath": session.partcad_ctx.config_path, "root": session.partcad_ctx.name},
                )
                _load_package_contents(session, session.partcad_ctx.name)
            else:
                session.emitter.signal(events.PACKAGE_LOAD_FAILED)
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
        if getattr(session.partcad_ctx, "broken", False):
            raise Exception("Package YAML file is not found")
        session.emitter.emit(
            events.PACKAGE_LOADED,
            {"configPath": session.partcad_ctx.config_path, "root": session.partcad_ctx.name},
        )
        _load_package_contents(session, session.partcad_ctx.name)
    except session.partcad.exception.NeedsUpdateException:
        session.emitter.signal(events.NEEDS_UPDATE)
    except Exception as e:  # pylint: disable=broad-except
        session.emitter.signal(events.PACKAGE_LOAD_FAILED)
        if session.partcad_ctx and not getattr(session.partcad_ctx, "broken", False):
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


def render_objects(session, params):
    """Render/export parts, assemblies, sketches, or interfaces to files.

    Backs both `pc export` (3D formats) and `pc render` (2D projections); the CLI
    passes the ``format`` and the ``label`` ("Export"/"Render"). ``output_dir``,
    when given, is resolved to an absolute path by the CLI so it lands in the
    user's working directory (the daemon runs elsewhere).
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

    with pc.logging.Process(params.get("label", "Render"), package):
        ctx.option_create_dirs = params.get("create_dirs", False)
        if params.get("recursive"):
            packages = [p["name"] for p in ctx.get_all_packages(parent_name=package, has_stuff=True)]
        else:
            packages = [package]

        for package in packages:
            if object_name is not None:
                package, object_name = pc.utils.resolve_resource_path(package, object_name)

            if object_name is None:
                ctx.render(project_path=package, format=fmt, output_dir=output_dir)
            else:
                sketches, interfaces, parts, assemblies = [], [], [], []
                if params.get("sketch"):
                    sketches.append(object_name)
                elif params.get("interface"):
                    interfaces.append(object_name)
                elif params.get("assembly"):
                    assemblies.append(object_name)
                else:
                    parts.append(object_name)
                prj = ctx.get_project(package)
                prj.render(
                    sketches=sketches,
                    interfaces=interfaces,
                    parts=parts,
                    assemblies=assemblies,
                    format=fmt,
                    output_dir=output_dir,
                )
    return None


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

    if kind == "part":
        package = ctx.resolve_package_path(params.get("package") or ".")
    else:
        package = params.get("package") if params.get("package") is not None else "."
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        raise JsonRpcError(USAGE_ERROR, "Failed to retrieve the project.")

    from partcad.actions.part import convert_part_action
    from partcad.actions.sketch import convert_sketch_action

    if kind == "part":
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

        packages = [pkg_obj(ctx.get_project(n)) for n in project.get_child_project_names()]

    sketches = [
        {**s.config, "item_path": (os.path.join(project.config_dir, s.path) if s.path else None)}
        for s in project.sketches.values()
    ]
    interfaces = [{**i.config, "item_path": None} for i in project.interfaces.values()]
    parts = [
        {**p.config, "item_path": (os.path.join(project.config_dir, p.path) if p.path else None)}
        for p in project.parts.values()
    ]
    assemblies = [
        {**a.config, "item_path": (os.path.join(project.config_dir, a.path) if a.path else None)}
        for a in project.assemblies.values()
    ]
    session.emitter.emit(
        events.ITEMS,
        {
            "name": name,
            "packages": packages,
            "sketches": sketches,
            "interfaces": interfaces,
            "parts": parts,
            "assemblies": assemblies,
        },
    )
    info(session, {})
