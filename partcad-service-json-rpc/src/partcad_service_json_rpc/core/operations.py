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

import os
import uuid

from packaging.specifiers import SpecifierSet

from . import events

_PART_AI_PROPERTIES = [
    "type",
    "provider",
    "desc",
    "tokens",
    "model",
    "temperature",
    "top_p",
    "top_k",
]


def _qualified(package: str, name: str) -> str:
    return package + ":" + name


# ---- inspection ------------------------------------------------------------


def inspect_part(session, params):
    """Instantiate and show a part in the connected CAD viewer."""
    ctx = session.partcad_ctx
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
    ctx = session.partcad_ctx
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
    ctx = session.partcad_ctx
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
    ctx = session.partcad_ctx
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
    ctx = session.partcad_ctx
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
    ctx = session.partcad_ctx
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
    ctx = session.partcad_ctx
    if ctx is None:
        return None
    package, name = params["package"], params["name"]
    with session.partcad.logging.Process("Export", package, name):
        assembly = ctx.get_assembly(_qualified(package, name), params.get("params"))
        if assembly:
            assembly.render(ctx, params["type"], filepath=params["path"])
    session.emitter.signal(events.EXPORT_PART_DONE)
    return None


# ---- generative design -----------------------------------------------------


def _apply_ai_config(project, part_name, config):
    part_config = project.get_part_config(part_name)
    update = {}
    for prop in _PART_AI_PROPERTIES:
        if prop in config:
            if config[prop] is not None:
                part_config[prop] = config[prop]
                update[prop] = config[prop]
            else:
                part_config.pop(prop, None)
                update[prop] = None
    if update:
        project.update_part_config(part_name, update)


def ai_regenerate(session, params):
    """Regenerate an AI-authored part with an updated config, then show it."""
    ctx = session.partcad_ctx
    if ctx is None:
        return None
    package, name = params["package"], params["name"]
    config = params.get("config", {})
    with session.partcad.logging.Process("Regenerate", package, name):
        try:
            project = ctx.get_project(package)
            _apply_ai_config(project, name, config)
            if name in project.parts:
                del project.parts[name]
            part = ctx.get_part(_qualified(package, name))
            part.regenerate()
        except Exception as e:
            session.partcad.logging.exception(e)
            raise
    return inspect_part(session, {"package": package, "name": name, "params": config.get("params")})


def ai_change(session, params):
    """Apply a natural-language change to an AI-authored part, then show it."""
    ctx = session.partcad_ctx
    if ctx is None:
        return None
    package, name = params["package"], params["name"]
    config = params.get("config", {})
    with session.partcad.logging.Process("Change", package, name):
        try:
            project = ctx.get_project(package)
            _apply_ai_config(project, name, config)
            if name in project.parts:
                del project.parts[name]
            part = ctx.get_part(_qualified(package, name))
            part.do_change(change=config.get("change", None))
            del project.parts[name]
        except Exception as e:
            session.partcad.logging.exception(e)
            raise
    return inspect_part(session, {"package": package, "name": name, "params": config.get("params")})


# ---- authoring -------------------------------------------------------------


def add_part(session, params):
    """Add a part to a package from an existing file."""
    ctx = session.partcad_ctx
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
    ctx = session.partcad_ctx
    if ctx is None:
        return None
    kind, path, package = params["kind"], params["path"], params["package"]
    session.emitter.info("Adding assembly %s" % path)
    with session.partcad.logging.Process("AddAssy", path):
        project = ctx.get_project(package)
        project.add_assembly(kind, path)
    return None


# ---- package helpers -------------------------------------------------------


def package_path(session, params):
    """Resolve a package's directory and hand it back to a client callback."""
    ctx = session.partcad_ctx
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
    ctx = session.partcad_ctx
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
    ctx = session.partcad_ctx
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


# ---- telemetry -------------------------------------------------------------


def telemetry_start(session, params):
    """Start a telemetry span and return its id.

    A thin client (the CLI) brackets a command in a span so the daemon's
    telemetry subsystem reports it upstream. Attributes are coerced to strings,
    matching how the CLI has always tagged its top-level span.
    """
    pc = session.ensure_partcad()
    pc.telemetry.once()
    attributes = {k: str(v) for k, v in (params.get("attributes") or {}).items()}
    span = pc.telemetry.tracer.start_span(params["name"], attributes=attributes)
    span_id = uuid.uuid4().hex
    session.spans[span_id] = span
    return {"span": span_id}


def telemetry_end(session, params):
    """End a previously started telemetry span."""
    span = session.spans.pop(params.get("span"), None)
    if span is None:
        return None
    trace = session.partcad.telemetry.trace
    if params.get("status") == "error":
        span.set_status(trace.Status(trace.StatusCode.ERROR, params.get("message")))
        if params.get("message"):
            span.set_attribute("error", params["message"])
    span.end()
    return None


# ---- lifecycle -------------------------------------------------------------


def activate(session, params):
    """Load PartCAD, verify version, run health checks, and signal readiness."""
    try:
        session.load_partcad()
        if session.partcad.__version__ not in SpecifierSet(">=0.7.146"):
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
            if session.partcad_ctx and not session.partcad_ctx.broken:
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
        if session.partcad_ctx.broken:
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
        if session.partcad_ctx and not session.partcad_ctx.broken:
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


def _load_package_contents(session, name="//"):
    ctx = session.partcad_ctx
    with session.partcad.logging.Process("Load", name):
        project = ctx.get_project(name)
        if project is None or project.broken:
            if project is not None and not project.broken:
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
