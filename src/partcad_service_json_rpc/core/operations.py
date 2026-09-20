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

import contextlib
import hashlib
import math
import os
import traceback
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import yaml
from packaging.specifiers import SpecifierSet

from partcad_utils import conda as pc_conda
from partcad_utils import config_report
from partcad_utils.utils import directory_size_mb, split_recursive_object

from ..rpc.dispatcher import JsonRpcError
from . import events

# PartCAD-specific JSON-RPC error code: a partcad.yaml could not be parsed. The
# CLI turns this into its "Invalid configuration file" message + exit code.
INVALID_CONFIG = -32001
# A user/usage error (bad argument, object not found, unsupported conversion).
# The CLI turns this into click.UsageError (exit code 2), matching the old
# in-process commands.
USAGE_ERROR = -32002
# An analysis that was asked and produced no answer: the implementation could
# not run here (no solver, no mesher, an unbuildable sandbox, a crash). The
# message is the report `partcad.cae.dysfunction_report()` wrote, and it is the
# answer to the user's question -- so it carries a code of its own rather than
# INTERNAL_ERROR, which would log a traceback on the daemon for something that
# is not a fault of the machinery. The CLI has no special case for it, which is
# what is wanted: an unrecognised code becomes a click.ClickException carrying
# the message, printed as it stands and exiting 1.
ANALYSIS_FAILED = -32003


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


def _request(params, default="."):
    """The package, the object and whether the request reaches below that package.

    ``-r`` and a ``...`` suffix on a package name are the same request written
    two ways, and either turns recursion on: ``//pub/examples...`` is
    ``-P //pub/examples -r``, and ``...:bolt`` is every bolt from here down.
    The suffix can also say *where* the walk starts, which a flag cannot, so an
    object name carrying one selects the subtree -- exactly as a fully
    qualified object name already selects a package over ``--package``.

    Every operation that takes a package goes through this, so that one
    spelling cannot come to mean one thing to ``pc list`` and another to
    ``pc render``. ``default`` is what the operation reads an absent package
    as, which is not the same everywhere (``pc search`` walks from the root,
    ``pc lint`` from the current package).
    """
    package, object_name, recursive = split_recursive_object(
        params.get("package") if params.get("package") else default,
        params.get("object"),
    )
    return package, object_name, recursive or bool(params.get("recursive"))


def _object_kind(params) -> str:
    """Which kind of object the flags of a request name.

    The same five flags on every command that takes an object, read in the same
    order, so that ``pc render -s`` and ``pc test -s`` cannot disagree about
    what ``-s`` selects. A part is what an object is when nothing says
    otherwise.
    """
    for kind in ("sketch", "interface", "assembly", "scene"):
        if params.get(kind):
            return kind
    return "part"


def _targets(ctx, pc, packages, object_name, kind):
    """The ``(package, object)`` pairs that a named object resolves to, where it exists.

    What a recursive run over a named object is: each package of the subtree is
    asked for its own object of that name, and the ones that have none are
    passed over in silence. Reporting them would mean thirty-seven "bolt is not
    found" lines and a non-zero exit for a tree in which three packages have a
    bolt, which is the opposite of what asking for ``...:bolt`` means.

    Deduplicated, because a name that carries a package of its own
    (``//elsewhere:bolt``) resolves to the same pair whichever package it was
    reached from -- one target rather than forty.

    An empty result is the one failure this has: the object is nowhere in the
    subtree, and the caller says so once.
    """
    targets = []
    seen = set()
    for package in packages:
        target, name = pc.utils.resolve_resource_path(package, object_name)
        if (target, name) in seen:
            continue
        seen.add((target, name))
        prj = ctx.get_project(target)
        if prj is None or not prj.declares_object(kind, name):
            continue
        targets.append((target, name))
    return targets


def _nowhere_message(object_name, package) -> str:
    """The one failure a walk over a named object can have, in words.

    One sentence, said once, wherever the walk was made from -- rather than the
    per-package "is not found" that a subtree of forty packages would otherwise
    produce thirty-seven of.
    """
    return "%s is not found in %s or in any package below it" % (object_name, package)


def _nowhere(pc, object_name, package) -> None:
    """Report that failure through the log, the way each operation reports its own."""
    pc.logging.error(_nowhere_message(object_name, package))


def _refuse_recursion(params) -> None:
    """Refuse a ``...`` on an operation whose answer is about one object.

    A bill of materials, an assembly instruction book, a CAE model, a quote, a
    viewer window and a converted declaration are each one thing about one
    object, so there is no obvious meaning for "all of them" to have: one
    merged answer and a sequence of answers are both defensible, and guessing
    between them is worse than saying so.

    Said outright rather than left to happen. Without this the suffix reaches
    ``resolve_resource_path``, which turns ``...`` into a ``*`` naming no
    package at all, and the user is told that ``//*:frame`` is not found --
    about a request nobody made.
    """
    _, _, recursive = _request(params)
    if recursive:
        raise JsonRpcError(
            USAGE_ERROR,
            "'...' asks about a whole subtree of packages; this command answers about one object. "
            "Name the object without the '...'.",
        )


def _resolve_object(ctx, pc, params):
    """The ``(package, name)`` of the object a request names.

    ``package`` is the package that *owns* the object, which is not always the
    one the request selected: an object given as ``//other/package:name`` is
    produced there, whatever ``--package`` said. Returns ``None`` when the
    selected package is not loaded, having said so, the way every other
    context-aware operation reports it.

    *One* object, so the operations that resolve through this are exactly the
    ones a ``...`` has no meaning for; see ``_refuse_recursion``.
    """
    object_name = params.get("object")
    if not object_name:
        raise JsonRpcError(USAGE_ERROR, "No object is given")
    _refuse_recursion(params)

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


def inspect_scene(session, params):
    """Instantiate and show a scene."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    package, name = params["package"], params["name"]
    with session.partcad.logging.Process("Inspect", package, name):
        scene = ctx.get_scene(_qualified(package, name), params.get("params"))
        if scene:
            scene.show()
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
            # Scenes first: an ASSY file a scene points at is not an assembly,
            # and opening it should inspect what the package says it is.
            for name, scene in prj.scenes.items():
                if hasattr(scene, "orig_name") and scene.name != scene.orig_name:
                    continue
                if scene.path is not None and os.path.exists(scene.path) and os.path.samefile(scene.path, path):
                    for paramed in _instances_of(prj.scenes, name):
                        del prj.scenes[paramed]
                    session.emitter.emit(
                        events.EXECUTE,
                        {"command": "partcad.inspectScene", "args": [{"name": name, "pkg": prj_name}, {}, True]},
                    )
                    return
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


def export_scene(session, params):
    """Render a scene to a file."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    package, name = params["package"], params["name"]
    with session.partcad.logging.Process("Export", package, name):
        scene = ctx.get_scene(_qualified(package, name), params.get("params"))
        if scene:
            scene.render(ctx, params["type"], filepath=params["path"])
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


def add_scene(session, params):
    """Add a scene to a package from an existing file."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    kind, path, package = params["kind"], params["path"], params["package"]
    session.emitter.info("Adding scene %s" % path)
    with session.partcad.logging.Process("AddScene", path):
        project = ctx.get_project(package)
        project.add_scene(kind, path)
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


# The 'partcad.yaml' section each kind of object 'pc add' can create is
# declared in.
_ADD_SECTIONS = {
    "part": "parts",
    "assembly": "assemblies",
    "scene": "scenes",
    "sketch": "sketches",
    "software": "software",
}


def add_object(session, params):
    """Add a part, assembly, scene or piece of software to a package.

    Two forms. Given ``path``, the package is pointed at a file it already has:
    the CLI resolves it to an absolute path (it and the daemon do not share a
    working directory), ``Project._validate_path`` rejects anything outside the
    package, and messages report the path relative to the package.

    Given ``url``, there is no file yet. It is fetched once - here, because the
    daemon is what has the context and the network - so that the declaration can
    be written with the ``fileHash`` of what came back. See
    ``partcad.actions.add``.
    """
    import asyncio
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

    config = {}
    if params.get("desc"):
        config["desc"] = params["desc"]

    url = params.get("url")
    if url:
        from partcad.actions.add import add_object_from_url_async

        section = _ADD_SECTIONS.get(obj_kind)
        if section is None:
            raise JsonRpcError(USAGE_ERROR, "ERROR: '%s' cannot be added from a URL." % obj_kind)
        try:
            name = asyncio.run(
                add_object_from_url_async(ctx, package_obj, section, url, kind=params.get("kind"), config=config)
            )
        except Exception as e:  # pylint: disable=broad-except
            # Without the bytes there is no hash, and an unpinned declaration is
            # what fetching it here exists to avoid - so this fails rather than
            # writing one.
            raise JsonRpcError(USAGE_ERROR, "ERROR: Failed to fetch '%s': %s" % (url, e))
        finally:
            _invalidate_context(session, params)
        return {"name": name}

    path = params["path"]
    if not Path(path).exists():
        raise JsonRpcError(USAGE_ERROR, "ERROR: The part file '%s' does not exist." % package_obj.rel_path(path))

    try:
        if obj_kind == "part":
            from partcad.actions.part import add_part_action

            added = add_part_action(package_obj, params["kind"], path, config)
        elif obj_kind == "software":
            with pc.logging.Process("AddSoftware", package_obj.name):
                added = package_obj.add_software(path, config)
        elif obj_kind == "scene":
            with pc.logging.Process("AddScene", package_obj.name):
                added = package_obj.add_scene(params["kind"], path, config)
                if added:
                    Path(path).touch()
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
    """Import a part, assembly or scene into a package, copying (and maybe converting) it.

    Served by the daemon rather than the client because the work runs through
    sandboxed wrappers: importing an assembly or a scene drives the reader the
    ``import:`` declaration for that format names -- one PartCAD ships, or one a
    plugin package does -- and ``--target-format`` converts through the same
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

        if obj_kind == "scene":
            from partcad.actions.scene import import_scene_action

            for key in ("ignoreCollision", "modelPaths"):
                if params.get(key) is not None:
                    config[key] = params[key]
            # Required, with no default. It used to default to 'world', which
            # was the only scene format PartCAD read; every arrangement format
            # now belongs to a simulation engine's plugin package, so a default
            # could only ever name a type that does not resolve -- and would
            # report that as a broken package rather than as a missing argument.
            scene_type = params.get("scene_type")
            if not scene_type:
                raise JsonRpcError(
                    USAGE_ERROR,
                    "Importing a scene needs the format to read it as ('scene_type'): a format a package "
                    "declares under 'import:' with 'scene' among its 'kinds', named through that package "
                    "(for example 'sim-gazebo:world').",
                )
            try:
                name = import_scene_action(package_obj, scene_type, source, config)
            except Exception as e:  # pylint: disable=broad-except
                pc.logging.exception("Error importing scene")
                raise JsonRpcError(USAGE_ERROR, "Error importing scene: %s" % e) from e
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
    elif project.get_scene_config(object_name):
        obj = project.get_scene(object_name)
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
                "scenes": ctx.stats_scenes,
                "scenesInstantiated": ctx.stats_scenes_instantiated,
                "size": ctx.stats_memory,
            },
            "version": session.partcad.__version__,
        },
    )
    return None


def info_object(session, params):
    """Show detailed information about a part, assembly, scene, interface, sketch, or software.

    Ported verbatim from the CLI `info` command: with no object name it reports
    the package's info, otherwise the object's configuration and info. Output is
    emitted through PartCAD logging so it renders exactly as before.
    """
    from pprint import pformat

    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad

    selected, object_name, recursive = _request(params, None)
    # '-p <name>=<value>' arrives as a list of strings; every accessor below
    # takes a mapping. Built here rather than passed through, because a list
    # reaches 'Project.get_object' as something it cannot merge.
    param_dict = {}
    for kv in params.get("params") or []:
        if "=" in kv:
            key, value = kv.split("=", 1)
            param_dict[key] = value

    package_name = ctx.resolve_package_path(selected)
    package_obj = ctx.get_project(package_name)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package_name)
        return None
    package_name = package_obj.name

    if object_name is None:
        # '//pub/examples...' with no object: the package and every package
        # below it, each reported as this reports one.
        if recursive:
            packages = [p["name"] for p in ctx.get_all_packages(parent_name=package_name, has_stuff=False)]
        else:
            packages = [package_name]
        for name in packages:
            project = ctx.get_project(name)
            if project is None:
                continue
            if recursive:
                pc.logging.info("PACKAGE: %s" % name)
            for k, v in project.info().items():
                pc.logging.info("INFO: %s: %s" % (k, pformat(v)))
        return None

    # 'pc info' has no '-r' of its own; '...' is how it is asked for one, which
    # is the whole reason the recursion is written on the package rather than
    # spelled as a flag on every command that could want it.
    kind = "software" if params.get("software") else _object_kind(params)
    if recursive:
        packages = [p["name"] for p in ctx.get_all_packages(parent_name=package_name, has_stuff=False)]
        targets = _targets(ctx, pc, packages, object_name, kind)
        if not targets:
            _nowhere(pc, object_name, package_name)
            return None
    else:
        # Resolve the object against the package '--package' names, not against
        # the current one: 'get_current_project_path()' as the base drops the
        # flag for every object name that does not carry a '//package:' prefix
        # of its own, which is the ordinary way to spell one. A name that does
        # carry a prefix still wins over the flag.
        targets = [pc.utils.resolve_resource_path(package_name, object_name)]

    for package, name in targets:
        path = _qualified(package, name)

        if kind == "assembly":
            obj = ctx.get_assembly(path, params=param_dict)
        elif kind == "scene":
            obj = ctx.get_scene(path, params=param_dict)
        elif kind == "interface":
            obj = ctx.get_interface(path, params=param_dict)
        elif kind == "sketch":
            obj = ctx.get_sketch(path, params=param_dict)
        elif kind == "software":
            # Resolved through the package rather than through a context
            # accessor: software is not a shape, and none of what 'ctx.get_*'
            # does for one - parameters, instantiation, the shape cache -
            # applies to a file.
            project = ctx.get_project(package)
            obj = project.get_software(name) if project is not None else None
        else:
            obj = ctx.get_part(path, params=param_dict)

        if obj is None:
            pc.logging.error("Object %s not found" % path)
        else:
            if recursive:
                # Which of the objects that answered to the name this is. One
                # report needs no heading; several run into each other without
                # one.
                pc.logging.info("OBJECT: %s" % path)
            pc.logging.info("CONFIGURATION: %s" % pformat(obj.config))
            for k, v in obj.info().items():
                pc.logging.info("INFO: %s: %s" % (k, pformat(v)))
    return None


def open_tools(session, params):
    """The applications this workspace's packages declare, for `pc open`.

    The one thing `pc open` needs the package graph for, and the reason it is
    answered here: opening a file is deliberately client-side work -- the window
    belongs to whoever ran the command, and a daemon can be remote -- but
    *which* applications exist is a fact about the packages a workspace imports,
    and only this side has those. So the client asks what is declared, and still
    does the opening itself. There is no method for opening a file and there
    must not be one.

    Only what a package declares is returned. PartCAD's own applications ship in
    the wheel the client is running out of, which reads them straight off disk
    (see `partcad_client.external.builtin_tools`); sending them over the wire as
    well would mean a client whose daemon is a different release quietly gets
    that release's table.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad

    builtin = pc.output.BUILTIN_PACKAGES[pc.output.OPEN]
    declared = {}
    # 'has_stuff=False': a plugin package declares implementations and no
    # objects at all, so the default filter - which keeps only packages holding
    # sketches, parts, assemblies or scenes - would drop precisely the ones this
    # is looking for.
    for package_name in ctx.get_all_packages(has_stuff=False):
        name = package_name["name"] if isinstance(package_name, dict) else package_name
        if name == builtin:
            continue
        project = ctx.get_project(name)
        section = getattr(project, "config_obj", {}).get(pc.output.OPEN) if project else None
        if not isinstance(section, dict):
            continue
        for tool_name, config in section.items():
            if isinstance(config, dict):
                declared[tool_name] = config
    return {"tools": declared}


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
    elif kind == "scene":
        # The third kind of object a file can hold: an arrangement rather than a
        # shape or a drawing. Nothing asks for it today -- `pc open` refuses a
        # scene it would have to convert, because every arrangement format
        # belongs to a plugin package an ad-hoc context cannot reach -- and it is
        # here because the machinery is the part conversion's. See
        # `partcad.adhoc.convert.convert_scene_file`.
        from partcad.adhoc.convert import convert_scene_file as convert_fn
        from partcad.shape import SCENE_EXTENSION_MAPPING as mapping
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
    noun = "sketch type" if kind == "sketch" else ("scene type" if kind == "scene" else "type")
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


def adhoc_render(session, params):
    """Render a CAD or sketch file to a 2D projection, ad-hoc (no package/context).

    The sibling of ``adhoc_convert`` for the other thing an output file can be,
    and the same pure file operation: paths arrive absolute from the CLI, and a
    type the caller left unsaid is inferred from the file name. The input type
    comes from the part/sketch mappings as it does for a conversion; the *output*
    type comes from the projections instead, which is the whole difference.

    ``view``, ``viewport_origin`` and ``viewport_up`` aim the projection, exactly
    as they do for ``render.objects`` -- with no ``partcad.yaml`` to configure a
    viewport in, this is the only way to ask for one.
    """
    from pathlib import Path

    from partcad.shape import RENDER_EXTENSION_MAPPING

    pc = session.ensure_partcad()
    kind = params.get("kind", "part")
    if kind == "part":
        from partcad.adhoc.render import render_cad_file as render_fn
        from partcad.shape import PART_EXTENSION_MAPPING as input_mapping
    elif kind == "sketch":
        from partcad.adhoc.render import render_sketch_file as render_fn
        from partcad.shape import SKETCH_EXTENSION_MAPPING as input_mapping
    else:
        # Named rather than fallen through to the sketch renderer: an assembly
        # or a scene is exactly what cannot be rendered without the package
        # that names its contents, so answering with a sketch of it would be
        # answering a different question. The CLI offers the two subcommands
        # and nothing else; a client speaking the protocol directly can ask.
        raise JsonRpcError(USAGE_ERROR, "Cannot render '%s' ad-hoc. Supported kinds: part, sketch" % kind)

    input_path = Path(params["input_filename"])
    output_filename = params.get("output_filename")
    output_path = Path(output_filename) if output_filename else None

    input_ext_to_type = {".%s" % v: k for k, v in input_mapping.items()}
    # '.jpeg' alongside the '.jpg' the mapping declares: the mapping says what
    # extension a projection is *written* with and so holds one per format, but
    # a file already named '.jpeg' is just as clearly a JPEG.
    output_ext_to_type = {".%s" % v: k for k, v in RENDER_EXTENSION_MAPPING.items()}
    output_ext_to_type[".jpeg"] = "jpeg"

    input_type = params.get("input_type") or input_ext_to_type.get(input_path.suffix.lower())
    output_type = params.get("output_type") or (
        output_ext_to_type.get(output_path.suffix.lower()) if output_path else None
    )

    noun = "sketch type" if kind == "sketch" else "type"
    if not input_type:
        pc.logging.error("Cannot infer input %s. Please specify --input explicitly." % noun)
        return None
    if not output_type:
        pc.logging.error("Cannot infer the projection to render. Please specify --output explicitly.")
        return None
    if output_type not in RENDER_EXTENSION_MAPPING:
        # Checked before the extension lookup below, which would otherwise
        # raise KeyError for a type nobody projects to and turn a bad request
        # into an internal error.
        raise JsonRpcError(
            USAGE_ERROR,
            "Cannot render to '%s'. Supported projections: %s"
            % (output_type, ", ".join(sorted(RENDER_EXTENSION_MAPPING))),
        )
    if output_path is None:
        output_path = input_path.with_suffix(".%s" % RENDER_EXTENSION_MAPPING[output_type])

    from partcad.render import resolve_viewport

    try:
        render_opts = resolve_viewport(
            params.get("view"),
            params.get("viewport_origin"),
            params.get("viewport_up"),
        )
    except ValueError as e:
        raise JsonRpcError(USAGE_ERROR, str(e)) from e

    try:
        pc.logging.info("Rendering %s (%s) to %s (%s)..." % (input_path, input_type, output_path, output_type))
        render_fn(str(input_path), input_type, str(output_path), output_type, **render_opts)
        pc.logging.info("Render complete: %s" % output_path)
    except ValueError as e:
        # A format that only means anything inside a package ('.urdf', '.assy')
        # is inferable from the filename, so it reaches here even though the
        # CLI's choices exclude it. Nothing was attempted and nothing could have
        # been: a usage error, not a failed render.
        raise JsonRpcError(USAGE_ERROR, str(e))
    except Exception as e:  # pylint: disable=broad-except
        pc.logging.error("Failed to render: %s" % e)
    return None


async def _test_async(ctx, pc, packages, filter_prefix, sketch, interface, assembly, scene, object_name):
    import asyncio

    from partcad.test.all import tests as all_tests

    tasks = []
    tests_to_run = all_tests(pc.user_config.threads_max)
    if filter_prefix:
        tests_to_run = list(filter(lambda t: t.name.startswith(filter_prefix), tests_to_run))

    scheduled = set()
    for package in packages:
        obj = object_name
        target = package
        if obj:
            # Resolve the object against the package being tested, not against
            # the current one. 'get_current_project_path()' as the base drops
            # '--package' for every object name without a '//package:' prefix of
            # its own, and on a recursive run it resolves every iteration to that
            # same current package -- so the one object was tested once per
            # package in the subtree instead of once in each of them. A name that
            # does carry a prefix still names its own package, exactly as a
            # recursive render resolves one (see '_render_packages_async').
            target, obj = pc.utils.resolve_resource_path(package, obj)
        # A '//elsewhere:name' resolves to the same pair whatever package it was
        # reached from, so a recursive run would otherwise schedule that one
        # object once per package in the subtree and report it as many times. An
        # unqualified name resolves to a different package each time, so it
        # still runs in each of them.
        if (target, obj) in scheduled:
            continue
        scheduled.add((target, obj))
        prj = ctx.get_project(target)
        if prj is None:
            # Reachable through a qualified object name: '--package' is checked
            # by the caller, but '//elsewhere:name' names a package of its own.
            pc.logging.error("Package %s is not found" % target)
            continue
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
            elif scene:
                shape = prj.get_scene(obj)
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
    selected, object_name, recursive = _request(params)
    package = ctx.resolve_package_path(selected)
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name

    with pc.logging.Process("Test", package):
        if recursive:
            all_packages = ctx.get_all_packages(parent_name=package)
            if ctx.stats_git_ops:
                pc.logging.info("Git operations: %s" % ctx.stats_git_ops)
            packages = [p["name"] for p in all_packages]
        else:
            packages = [package]

        if recursive and object_name:
            # Only the packages that have such an object. Without this, testing
            # one object over a subtree reports it missing from every package
            # that does not declare it -- which for a name like 'bolt' is most
            # of them, and is not what asking for every bolt means.
            targets = _targets(ctx, pc, packages, object_name, _object_kind(params))
            if not targets:
                _nowhere(pc, object_name, package)
                return None
            packages = [target for target, _ in targets]

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
                object_name,
            )
        )
    return None


async def _lint_async(ctx, pc, packages, filter_prefix):
    import asyncio

    from partcad.lint.all import get_linting_checks

    tasks = []
    lint_checks = get_linting_checks(pc.user_config.threads_max)
    if filter_prefix:
        lint_checks = list(filter(lambda check: check.name.startswith(filter_prefix), lint_checks))

    for package in packages:
        prj = ctx.get_project(package)
        tasks.extend([c.lint_log_wrapper(ctx, prj, t) for c in lint_checks for t in c.get_targets(ctx, prj)])
    await asyncio.gather(*tasks)


def lint_run(session, params):
    """Run linting checks on files within a package (recursively when asked)."""
    import asyncio

    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    selected, _, recursive = _request(params, "")
    package = ctx.resolve_package_path(selected)
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name

    with pc.logging.Process("Lint", package):
        if recursive:
            all_packages = ctx.get_all_packages(parent_name=package)
            if ctx.stats_git_ops:
                pc.logging.info("Git operations: %s" % ctx.stats_git_ops)
            packages = [p["name"] for p in all_packages]
        else:
            packages = [package]
        asyncio.run(_lint_async(ctx, pc, packages, params.get("filter")))
    return None


async def _simulate_async(ctx, pc, packages, object_name, is_assembly, filter_name):
    """Run every declared simulation of what was selected, one after another.

    Sequentially, and deliberately: a simulation plugin is a whole simulator
    running a physics model, so the machine is what limits how many of them fit
    at once, not the event loop -- and two of them competing for it would make
    both slower and neither more informative. It is also what keeps the log
    readable, which for a command whose whole output is a verdict per run is
    most of what it is for.
    """
    from partcad import simulation as pc_simulation

    targets = []
    if object_name:
        scheduled = set()
        for package in packages:
            # Resolved against the package being simulated, not against the
            # current one: 'get_current_project_path()' as the base drops
            # '--package' for every object name without a '//package:' prefix of
            # its own, and on a recursive run it resolves every iteration to
            # that same current package. The resolution a recursive test and a
            # recursive render already do -- and a '//elsewhere:name' that
            # resolves to one pair from every package is one simulation rather
            # than one per package.
            target, name = pc.utils.resolve_resource_path(package, object_name)
            if (target, name) in scheduled:
                continue
            scheduled.add((target, name))
            prj = ctx.get_project(target)
            if prj is None:
                raise JsonRpcError(USAGE_ERROR, "Package %s is not found" % target)
            if is_assembly:
                shape, kind = prj.get_assembly(name), "assembly"
            else:
                # Awaited, not 'get_part()': this is a coroutine, and a part a URDF,
                # MJCF or STEP assembly produces has to have that assembly built
                # before it exists. See 'Project.get_part_async()'.
                shape, kind = await prj.get_part_async(name), "part"
            if shape is None:
                raise JsonRpcError(USAGE_ERROR, "%s is not found" % _qualified(target, name))
            targets.append((kind, shape))
    else:
        for package in packages:
            prj = ctx.get_project(package)
            if prj is None:
                continue
            targets.extend(("part", shape) for shape in list(prj.parts.values()))
            targets.extend(("assembly", shape) for shape in list(prj.assemblies.values()))

    results = []
    for kind, shape in targets:
        for declaration in pc_simulation.of_shape(shape):
            if filter_name and declaration.name != filter_name:
                continue
            results.append(await pc_simulation.run_async(ctx, shape, kind, declaration))
    return results


def simulate_run(session, params):
    """Run the simulations a part or an assembly declares, and validate them."""
    import asyncio

    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    selected, object_name, recursive = _request(params)
    package = ctx.resolve_package_path(selected)
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name

    with pc.logging.Process("Simulate", package):
        if recursive:
            all_packages = ctx.get_all_packages(parent_name=package)
            packages = [p["name"] for p in all_packages]
        else:
            packages = [package]

        if recursive and object_name:
            # Only the packages that have such an object, so that walking a
            # subtree for one name is the simulations of the objects that
            # answer to it rather than a failure per package that does not.
            kind = "assembly" if params.get("assembly") else "part"
            targets = _targets(ctx, pc, packages, object_name, kind)
            if not targets:
                # A usage error, the way naming one object that does not exist
                # already is ('_simulate_async' raises the same for it): what
                # was asked for is not there, and nothing was run.
                raise JsonRpcError(USAGE_ERROR, _nowhere_message(object_name, package))
            packages = [target for target, _ in targets]

        results = asyncio.run(
            _simulate_async(
                ctx,
                pc,
                packages,
                object_name,
                params.get("assembly"),
                params.get("filter"),
            )
        )

    # Asking for something in particular and matching nothing is a failure;
    # walking a tree that happens to declare no simulation is not. The two look
    # identical here - an empty result list - and only the request tells them
    # apart, so it is the request that is consulted. Without this, 'pc sim -a'
    # on a name that does not exist reports success and exits 0.
    asked_for = [object_name, params.get("assembly"), params.get("filter")]
    named_one = any(value for value in asked_for)

    unmatched = False
    if not results:
        if named_one:
            unmatched = True
            pc.logging.error(
                "Nothing here declares a 'simulate:' section matching %s"
                % ", ".join("'%s'" % value for value in asked_for if value)
            )
        else:
            pc.logging.info("Nothing declares a 'simulate:' section here")
    for result in results:
        pc.logging.info(_simulation_line(result))
    failed = [result for result in results if result.failed]

    return {
        "simulations": [result.to_dict() for result in results],
        "total": len(results),
        "failed": len(failed),
        # What the CLI exits non-zero on, said once here rather than derived
        # from the list by every caller.
        "ok": not failed and not unmatched,
    }


def _simulation_line(result) -> str:
    """One run, as the single line the log reports it with."""
    if result.error is not None:
        verdict = "ERROR: %s" % result.error
    elif result.passed is None:
        verdict = "ran (no 'validation' to check it against)"
    else:
        verdict = "PASSED" if result.passed else "FAILED"
    return "%s: %s: %s" % (result.object_name, result.name, verdict)


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

            # The packages those environments were built from, which only the
            # conda a standalone bundle carries keeps here -- a host conda has a
            # package cache of its own, elsewhere, and PartCAD does not empty
            # caches it did not fill. Not nested under the directory above: the
            # cache outlives the environments, and a machine that has the one
            # without the other is what a previous half-reset leaves behind.
            conda_dir = os.path.join(user_config.internal_state_dir, pc_conda.ROOT_PREFIX_SUBDIR)
            if os.path.exists(conda_dir):
                with pc.logging.Action("Sandbox", "conda"):
                    shutil.rmtree(conda_dir)
                    pc.logging.info("Removed the conda package cache: '%s'" % conda_dir)

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

    with pc.logging.Process("Status", "global"):
        pc.logging.info("PartCAD version: %s" % pc.__version__)
        pc.logging.info("Internal data storage location: %s" % root)
        with pc.logging.Action("Status", "total"):
            pc.logging.info("Total internal data storage size: %.2fMB" % directory_size_mb(root))
        with pc.logging.Action("Status", "git"):
            pc.logging.info("Git cache size: %.2fMB" % directory_size_mb(os.path.join(root, "git")))
        with pc.logging.Action("Status", "tar"):
            pc.logging.info("Tar cache size: %.2fMB" % directory_size_mb(os.path.join(root, "tar")))
        with pc.logging.Action("Status", "sandbox"):
            pc.logging.info("Sandbox environments size: %.2fMB" % directory_size_mb(os.path.join(root, "sandbox")))
        with pc.logging.Action("Status", "conda"):
            pc.logging.info(
                "Conda package cache size: %.2fMB" % directory_size_mb(os.path.join(root, pc_conda.ROOT_PREFIX_SUBDIR))
            )
    return None


def daemon_status_config(session, params):
    """Report the daemon's own effective configuration.

    The daemon-side counterpart of `pc system status config`. The two differ on
    purpose: a daemon is warm and shared per workspace, so this is whatever its
    environment held when something first started it -- which is exactly why a
    caller's configuration travels with every `context.create` and is what the
    work is actually done under. This is the fallback that a client sending none
    gets, and the thing to read when a command behaved as though it had been
    invoked somewhere else.

    Secrets are taken out here, on the daemon, so that a value the client has no
    business holding never reaches the wire.
    """
    pc = session.ensure_partcad()
    with pc.logging.Process("StatusConfig", "global"):
        config_path = pc.user_config.get_config_path()
        if not os.path.exists(config_path):
            config_path += " (absent)"
        pc.logging.info("Configuration file: %s" % config_path)
        for key, value in config_report.resolved_options(pc.user_config):
            pc.logging.info("%s: %s" % (key, value))
    return None


def daemon_status_env(session, params):
    """Report the `PC_*` environment variables the daemon runs with.

    The daemon-side counterpart of `pc system status env`, and the report that
    cannot be worked out from the client at all: the daemon inherited the
    environment of whatever started it -- a shell, an editor, a previous day's
    session -- and nothing on the client side has a copy of it.

    `os.environ` rather than anything the configuration remembers: the question
    is what this process was handed, including the variables PartCAD binds no
    option to and the ones it does not recognise at all.
    """
    pc = session.ensure_partcad()
    with pc.logging.Process("StatusEnv", "global"):
        reported = list(config_report.environment())
        if not reported:
            pc.logging.info("No %s* environment variables are set" % config_report.ENV_PREFIX)
        for name, value in reported:
            pc.logging.info("%s=%s" % (name, value))
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
    # One object: the viewer shows a shape, and a verbal summary describes one.
    _refuse_recursion(params)
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

        # Resolve the object against the package '--package' selected, not
        # against the current one: 'get_current_project_path()' as the base drops
        # the flag for every object name without a '//package:' prefix of its
        # own. 'package' still holds the selected package here -- it was resolved
        # and checked above. A name that does carry a prefix still wins over the
        # flag, which is why the owning package is read back off 'package' below
        # rather than assumed to be the selected one.
        package, object_name = pc.utils.resolve_resource_path(package, object_name)
        path = _qualified(package, object_name)
        if params.get("assembly"):
            obj = ctx.get_assembly(path, params=param_dict)
        elif params.get("scene"):
            obj = ctx.get_scene(path, params=param_dict)
        elif params.get("interface"):
            obj = ctx.get_interface(path, params=param_dict)
        elif params.get("sketch"):
            obj = ctx.get_sketch(path, params=param_dict)
        else:
            obj = ctx.get_part(path, params=param_dict)

        if obj is None:
            pc.logging.error("Object %s is not found" % path)
            return None
        if params.get("verbal"):
            # The object's own package. 'obj' having been found means it is
            # loaded, so this never comes back None.
            summary = obj.get_summary(ctx.get_project(package))
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
    selected, _, recursive = _request(params)
    package = ctx.resolve_package_path(selected)
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

        if recursive:
            # A '/' has to follow the prefix, or '//sub' would also select the
            # unrelated sibling '//subwidget'.
            prefix = package if package.endswith("/") else package + "/"
            packages = [p["name"] for p in all_packages if p["name"] == package or p["name"].startswith(prefix)]
        else:
            packages = [package]
        stats = pc.actions.package.install(ctx, packages)

    session.emitter.info(
        "Installed %d sketches, %d parts, %d assemblies and %d software objects"
        % (stats["sketch"], stats["part"], stats["assembly"], stats["software"])
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
        if session.partcad.__version__ not in SpecifierSet(">=0.8.111"):
            session.emitter.error("Failed to activate PartCAD: PartCAD Python module is not up-to-date.")
            session.emitter.signal(events.ACTIVATE_FAILED)
            return None
        session.partcad.healthcheck.tests.run_healthchecks()
        session.emitter.signal(events.LOADED)
    except Exception as e:  # pylint: disable=broad-except
        # The traceback, not just the message. Activation covers importing (or
        # reloading) the whole of `partcad`, checking its version and running
        # every health check, so `str(e)` on its own can name neither the file
        # nor the operation: a reload failure reported exactly "'module' object
        # is not callable", which says nothing about where, and the client shows
        # this text as the only account of why the window is dead.
        #
        # Emitted rather than logged through `partcad.logging`: what failed may
        # be the import of `partcad` itself, in which case there is no logger.
        session.emitter.error(
            "Failed to activate PartCAD: %s.\nFollow instructions in the PartCAD's Explorer view.\n%s"
            % (e, traceback.format_exc())
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
    """Load and report the contents (packages/sketches/interfaces/parts/assemblies/scenes/software)."""
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


# The object kinds `pc list <kind>` renders identically (name + description
# table, optional package column when recursive). One operation serves them all;
# the CLI passes the kind. Output is emitted verbatim through PartCAD's logger so
# it renders exactly as the old in-process command did.
#
# The key is the name of the package attribute holding the objects, which is why
# 'software' looks singular here: the section is called that in both numbers.
_LIST_LABELS = {
    "materials": "PartCAD materials",
    "parts": "PartCAD parts",
    "sketches": "PartCAD sketches",
    "assemblies": "PartCAD assemblies",
    "scenes": "PartCAD scenes",
    "interfaces": "PartCAD interfaces",
    "software": "PartCAD software",
}

# The kinds whose recursive listing walks every package rather than only the
# ones with geometry in them. A package of firmware images has nothing to render
# and would be filtered out of the walk exactly as a package of interfaces is
# (see 'Context.get_packages', and the TODO there about the two).
_LIST_EVERY_PACKAGE = ("interfaces", "software", "materials")


def list_objects(session, params):
    """List a package's parts, sketches, assemblies, interfaces, materials or software."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    kind = params.get("kind", "parts")
    selected, _, recursive = _request(params)

    package = ctx.resolve_package_path(selected)
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name  # '//' may resolve to a differently-named package

    with pc.logging.Process("List" + kind.capitalize(), package):
        count = 0
        if recursive:
            # `list interfaces` and `list software` walk every package; the
            # others only those with content.
            has_stuff = kind not in _LIST_EVERY_PACKAGE
            packages = [p["name"] for p in ctx.get_all_packages(parent_name=package, has_stuff=has_stuff)]
        else:
            packages = [package]

        output = _LIST_LABELS.get(kind, "PartCAD objects") + ":\n"
        for project_name in packages:
            project = ctx.projects[project_name]
            # A snapshot, not the live dictionary: reading an object can
            # resolve another one into the package - an interface declared as
            # an alias takes its description from the interface it names - and
            # that registers it, which is a dictionary changing size while it
            # is being walked.
            for name, obj in sorted(getattr(project, kind).items()):
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
    selected, _, recursive = _request(params)
    package = ctx.resolve_package_path(selected)
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
    selected, _, recursive = _request(params)
    package = ctx.resolve_package_path(selected)
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
    selected, _, recursive = _request(params)
    package = ctx.resolve_package_path(selected)
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
    """Print the bill of materials of an assembly or a scene.

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
        # A scene lists what it holds the same way an assembly does, so it gets
        # the same bill of materials. Which one the name refers to is read from
        # the package's declarations rather than tried in turn: asking for the
        # assembly first would report "not found" for every scene.
        package_obj = ctx.get_project(package)
        is_scene = (
            package_obj is not None
            and package_obj.get_assembly_config(object_name) is None
            and package_obj.get_scene_config(object_name) is not None
        )
        assembly = ctx.get_scene(path, params=param_dict) if is_scene else ctx.get_assembly(path, params=param_dict)
        if assembly is None:
            # Name the kind that was looked for. 'is_scene' has already decided
            # which of the two this is, so there is nothing to be vague about,
            # and "Object" tells a user asking for an assembly the least useful
            # true thing: that something of some unnamed kind is missing.
            pc.logging.error("%s %s is not found" % ("Scene" if is_scene else "Assembly", path))
            return None

        bom_items = asyncio.run(
            assembly.get_bom_detailed_async(ctx, stop_at_purchasable=bool(params.get("stop_at_purchasable")))
        )

        items = [{"name": name, **entry} for name, entry in sorted(bom_items.items())]
        # 'total' counts the hardware, as it always has; the software of an
        # assembly is counted separately rather than added into it. Two boards
        # and the one image both of them run is not five of anything.
        result = {
            "assembly": path,
            "items": items,
            "total": sum(item["count"] for item in items if item.get("kind") != "software"),
            "totalSoftware": sum(item["count"] for item in items if item.get("kind") == "software"),
        }

        if not params.get("json"):
            pc.logging.info(_bom_output(result))
    return result


def _bom_output(result: dict) -> str:
    """The human-readable rendering of a BoM: one line item per line.

    The columns are sized from the content, not fixed the way `pc list` sizes
    its own: every name here carries the package it comes from, so the names are
    long and their length varies a lot from one BoM to the next.

    Software is listed under a heading of its own rather than interleaved with
    the hardware. What its "source" column says is not a vendor and an SKU -
    nobody sells a firmware image - but the package it comes from and the
    revision of that package, which is what identifies the file.
    """
    items = result["items"]
    output = "Bill of materials of %s:\n" % result["assembly"]
    if not items:
        return output + "\t<none>\n"

    hardware = [item for item in items if item.get("kind") != "software"]
    software = [item for item in items if item.get("kind") == "software"]

    output += _bom_table(hardware)
    output += "Total: %d\n" % result["total"]
    if software:
        output += "Software:\n"
        output += _bom_table(software)
        output += "Software total: %d\n" % result.get("totalSoftware", 0)
    return output


def _bom_table(items: list) -> str:
    """One block of BoM line items, with the columns sized from the content."""
    if not items:
        return "\t<none>\n"

    rows = []
    for item in items:
        if item.get("kind") == "software":
            # The package and the commit it was read at: the same name in the
            # same package is a different file once the package publishes again.
            source = item.get("package") or ""
            if item.get("revision"):
                source = "%s@%s" % (source, item["revision"])
            elif item.get("fileHash"):
                # No revision to name it by -- a package with no source tree of
                # its own has none -- so the hash of the file it pins is what is
                # left to identify a fetched image with.
                source = "%s %s" % (source, item["fileHash"])
        elif item.get("vendor") and item.get("sku"):
            # What to order, for the items that say so: buying one needs the
            # vendor and the SKU, not the name PartCAD knows it by.
            source = "%s %s" % (item["vendor"], item["sku"])
        else:
            source = ""
        rows.append((item["name"], str(item["count"]), source, item.get("desc") or ""))

    name_width = max(len(row[0]) for row in rows)
    count_width = max(len(row[1]) for row in rows)
    source_width = max(len(row[2]) for row in rows)

    # Where a folded description continues, counting the leading tab as one.
    indent = 1 + name_width + 2 + count_width + 2 + (source_width + 2 if source_width else 0)
    output = ""
    for name, count, source, desc in rows:
        line = "\t%s  %s" % (name.ljust(name_width), count.rjust(count_width))
        if source_width:
            line += "  %s" % source.ljust(source_width)
        line += "  " + desc.replace("\n", "\n" + " " * indent)
        output += line.rstrip() + "\n"
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


def cae_defaults(session, params):
    """Which implementation each CAE analysis runs under when nobody says otherwise.

    Needed by a client that offers to change it -- the IDE's FEA and CFD tabs
    have a field over the model -- because the answer is user configuration and
    not anything about the object on screen. Not context-aware: nothing here
    reads a package.
    """
    pc = session.partcad
    # '_caller_user_config' answers with the caller's configuration where one was
    # sent and the daemon's own where none was; either way the second half of the
    # pair is the configuration to read.
    _sent, config = _caller_user_config(pc, params)
    return {analysis: config.cae_implementation(analysis) for analysis in pc.cae.ANALYSES}


@contextlib.contextmanager
def _creating_dirs(ctx, enabled):
    """Turn `ctx.option_create_dirs` on for one request, and put it back.

    The daemon holds a context per workspace and keeps it warm, so anything set
    on it outlives the request that set it. `-p` on one `pc cam` would
    therefore go on creating directories for every later request served by that
    context -- including `pc export`, which never sets this at all and would
    quietly start making the directories it used to refuse to.

    A context manager rather than three `try:`/`finally:` blocks, because there
    are three requests that take this flag and the bug is not noticing that a
    fourth reads it.
    """
    previous = ctx.option_create_dirs
    ctx.option_create_dirs = bool(enabled)
    try:
        yield
    finally:
        ctx.option_create_dirs = previous


def cae_analyze(session, params):
    """Run a CAE analysis on a part and return the model it wrote and its findings.

    Backs ``pc cae fea`` and ``pc cae cfd``; ``analysis`` says which. The part
    declares the boundary conditions in a section of its own named after the
    analysis (``fea:``/``cfd:``, see ``partcad.cae``) and the implementation is
    whatever ``implementation`` -- or, failing that, the caller's user
    configuration -- names, as ``<package>:<file type>``.

    The model is written to ``<part>.<analysis>.<extension>`` beside the package,
    as it stands: which format that is, and whether it is 2D or 3D, is the
    implementation's decision and PartCAD does not convert it. ``inline`` asks
    for its bytes to come back base64-encoded as well, which is what the IDE's
    FEA and CFD tabs need -- a webview has no file system in reach, so a model it
    cannot be handed is a model it cannot draw.

    A part that declares no such section, or declares it wrongly, is a
    ``USAGE_ERROR`` carrying the sentence that says which: the answer the user
    asked for rather than a failure of the machinery, and the very text the IDE
    shows in the tab.
    """
    import asyncio

    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad

    analysis = params.get("analysis")
    if analysis not in pc.cae.ANALYSES:
        raise JsonRpcError(
            USAGE_ERROR,
            "Unknown analysis '%s'. PartCAD runs: %s" % (analysis, ", ".join(pc.cae.ANALYSES)),
        )

    resolved = _resolve_object(ctx, pc, params)
    if resolved is None:
        return None
    package, object_name = resolved
    path = _qualified(package, object_name)

    shape = ctx.get_part(path)
    if shape is None:
        # Only a part is analysed. An assembly is a set of parts that each have
        # their own boundary conditions, and a "load" on the whole of one says
        # nothing about which of its members carries it.
        raise JsonRpcError(USAGE_ERROR, "Part %s is not found" % path)

    with (
        pc.logging.Process(analysis.upper(), package, object_name),
        _creating_dirs(ctx, params.get("create_dirs", False)),
    ):
        try:
            result = asyncio.run(
                shape.analyze_async(
                    ctx,
                    analysis,
                    implementation=params.get("implementation") or None,
                    output_dir=params.get("output_dir") or None,
                )
            )
        except pc.cae.CaeConfigError as e:
            # "This part says nothing about FEA" and "what it says does not
            # parse" are both answers, and both are what the tab prints.
            raise JsonRpcError(USAGE_ERROR, str(e)) from e
        except pc.runtime.SandboxUnavailable as e:
            # No sandbox to run the analysis in is the same answer as an
            # implementation that was asked and could not run: the part has no
            # result, and the machine is why. Left to the dispatcher it came
            # back as an internal error with a traceback -- a bug report about
            # PartCAD rather than the two remedies the user needs. Reported the
            # way 'pc test' reports it, so the command, the check and the IDE's
            # tab say the same thing about the same machine.
            raise JsonRpcError(
                ANALYSIS_FAILED,
                pc.cae.dysfunction_report(
                    path,
                    analysis,
                    params.get("implementation") or "the configured implementation",
                    e,
                    remedy=pc.cae.NO_RUNTIME_REMEDY,
                ),
            ) from e
        except pc.cae.CaeFailed as e:
            # The implementation was asked and did not deliver. Reported as
            # `Shape.analyze_async()` wrote it -- which implementation was
            # asked, what it said, and which machine it did not work on -- so
            # that `pc cae fea`, `pc test -f fea` and the IDE's FEA tab all say
            # the same thing about the same machine. It is deliberately as loud
            # as the check's failure: a user who ran the command and got one
            # line, then ran the check and got the platform it failed on, was
            # being told less by the command that exists to be asked.
            raise JsonRpcError(ANALYSIS_FAILED, str(e)) from e

    if params.get("inline"):
        import base64

        try:
            with open(result["filepath"], "rb") as f:
                result["content"] = base64.b64encode(f.read()).decode("ascii")
        except OSError as e:
            # The findings are still worth having: an implementation that
            # reported them and then failed to leave the model where it said it
            # would has answered the more important half of the question.
            pc.logging.warning("Failed to read the %s model back: %s" % (analysis.upper(), e))
            result["content"] = None

    if not params.get("json"):
        pc.logging.info(pc.cae.findings_report(path, analysis, result["findings"]))
        pc.logging.info("%s model: %s" % (analysis.upper(), result["filepath"]))
    return result


def cam_route(session, params):
    """Produce the route files of the objects that declare one, and say where they went.

    Backs ``pc cam``. An object declares what is to be cut in its own
    ``manufacturing:`` section (see ``partcad.cam``), and the implementation is
    whatever
    ``implementation`` -- or, failing that, the object's own ``implementation:``,
    or the caller's ``camImplementation`` -- names, as ``<package>:<file type>``.

    ``object`` routes that one object and refuses if it declares nothing. With no
    ``object`` every sketch and part of the package that says how it is made --
    a machine or a job parameter under ``manufacturing:`` -- is routed and
    everything else is passed over in silence, which is
    what makes the command usable in a package where three parts of forty are
    cut. ``recursive`` does the same through the packages below this one.

    A whole-package run reports every object and then fails if any of them
    failed, rather than stopping at the first. A route is a file: an object
    whose section is wrong must not cost the other nineteen theirs, and a user
    who ran this over a package wants the list rather than the first line of it.
    """
    import asyncio

    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad

    selected, object_name, recursive = _request(params)
    package = ctx.resolve_package_path(selected)
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name

    # Which of an object's machines to write for. None lets each object take the
    # one it names, and refuses the ones that name several -- the sentence says
    # which they are, because a default nobody picked is a program for the wrong
    # machine.
    machine = params.get("machine")
    if recursive:
        packages = [p["name"] for p in ctx.get_all_packages(parent_name=package, has_stuff=True)]
    else:
        packages = [package]

    if recursive and object_name:
        # Only the packages that have such an object. A package of the subtree
        # that declares no object of that name has not failed to route one, and
        # counting it as a failure is what would make '...:panel' over a tree
        # exit non-zero for every tree but the one where every package has a
        # panel.
        targets = _targets(ctx, pc, packages, object_name, "sketch" if params.get("sketch") else "part")
        if not targets:
            _nowhere(pc, object_name, package)
            # Named among the failures as it was written, not qualified with the
            # package the walk started from: it is in none of them.
            return {"routes": [], "failed": [object_name]}
        packages = [target for target, _ in targets]

    with pc.logging.Process("CAM", package), _creating_dirs(ctx, params.get("create_dirs", False)):
        results, failures = asyncio.run(
            _route_packages_async(
                pc,
                ctx,
                packages,
                object_name,
                sketch=bool(params.get("sketch")),
                implementation=params.get("implementation") or None,
                machine=machine,
                output_dir=params.get("output_dir") or None,
                quiet_misses=bool(recursive and object_name),
            )
        )

    if not params.get("json"):
        for result in results:
            pc.logging.info(pc.cam.route_report(result["object"], result))
        if not results and not failures and not object_name:
            # Nothing was wrong and nothing was produced, which is a real answer
            # and one a user acting on an empty command line needs said out
            # loud: `pc cam` in a package where nothing says how it is made
            # otherwise looks exactly like a route that went somewhere the user
            # did not notice.
            #
            # Only where no object was named. A name that resolved to nothing
            # has already been reported as the object it is -- which is what the
            # user typed -- and saying that the package declares no
            # `manufacturing:` section on top of it answers a question nobody
            # asked, about a package that may be full of them.
            pc.logging.info("Nothing in %s declares how it is made, so no route was produced" % package)

    # The routes that were produced are returned whether or not others failed,
    # and the failure travels beside them as a name rather than as an exception.
    # Raising here discarded them at the RPC boundary: `pc cam --json` over a
    # package where one object of twenty is misconfigured printed nothing at
    # all, and the nineteen files on disk had no machine-readable record. What
    # the caller does with the pair is the caller's -- the CLI prints the array
    # and then exits non-zero, which is the behaviour this always documented.
    return {
        "routes": results,
        "failed": sorted(name for name, _ in failures),
    }


async def _route_packages_async(
    pc, ctx, packages, object_name, sketch, implementation, output_dir, machine=None, quiet_misses=False
):
    """Route the objects of every package named, reporting each as it lands.

    Bounded the way a recursive render is bounded, and for the same reason: what
    keeps the machine busy is the sandbox process budget, so enough objects to
    keep that budget full is all the concurrency there is any use for.

    Nothing is cancelled when one object fails. A route is a file, and a package
    interrupted half way through writing them is worse than one that finishes
    and reports.

    ``quiet_misses`` is a walk of a subtree for one name ('...:panel'). There a
    package that has the object but does not say how it is made has not failed
    to route anything -- it was never asked -- so it goes unreported, and only a
    walk that routed nothing at all is the failure.
    """
    import asyncio

    from partcad.sandbox_lock import process_slots

    # The packages PartCAD ships inside itself are loaded on demand, by the
    # first thing that asks what file types exist. Ask once here, before
    # anything runs, so that several objects arriving at that question together
    # do not each import them -- the same thing a recursive render does.
    pc.output.all_formats(ctx)

    shapes = []
    unresolved = []
    seen = set()
    for package in packages:
        target, obj = package, object_name
        if obj:
            # Resolved against the package being routed rather than the current
            # one: a '//elsewhere:name' names its own package whichever package
            # it was reached from, and an unqualified name means one object in
            # each of them. The same resolution a recursive render and a
            # recursive test do.
            target, obj = pc.utils.resolve_resource_path(package, obj)
            if (target, obj) in seen:
                continue
            seen.add((target, obj))
        prj = ctx.get_project(target)
        if prj is None:
            pc.logging.error("Package %s is not found" % target)
            if obj:
                # The same rule as the `not named` case below, one step
                # earlier: naming an object is asking about it, so failing to
                # find the *package* it named is as much a failure as failing
                # to find the object in a package that exists. Without this,
                # `pc cam //missing:panel` logged the error and exited 0.
                unresolved.append("%s:%s" % (target, obj))
            continue
        if obj is None:
            # The whole package: every sketch and part of it that says how it
            # is made, under 'manufacturing:'.
            shapes.extend(await prj.routable_shapes_async())
            continue

        if sketch:
            named = await prj.routable_shapes_async(sketches=[obj])
        else:
            named = await prj.routable_shapes_async(parts=[obj])
        if not named:
            # The getter has already said which object it could not find, and
            # in which package. What this adds is the failure itself: without
            # it a typo came back as an empty *success*, and a caller reading
            # the result rather than the log -- the IDE, or anything piping
            # `--json` -- saw a package where nothing needed routing.
            if not quiet_misses:
                unresolved.append("%s:%s" % (target, obj))
            continue
        shapes.extend(named)

    if quiet_misses and not shapes:
        # A walk of the subtree that routed nothing: the name is the one thing
        # that was asked about, so it is the one thing reported, once.
        unresolved.append(object_name)

    at_once = asyncio.Semaphore(max(1, process_slots.count))

    async def route(shape):
        async with at_once:
            return await shape.route_async(ctx, implementation=implementation, output_dir=output_dir, machine=machine)

    produced = await asyncio.gather(*[route(shape) for shape in shapes], return_exceptions=True)

    results, failures = [], [(name, None) for name in unresolved]
    for shape, result in zip(shapes, produced):
        name = "%s:%s" % (shape.project_name, shape.name)
        if not isinstance(result, BaseException):
            results.append(result)
            continue
        if isinstance(result, (pc.cam.CamConfigError, pc.cam.CamFailed)):
            # Both are answers to the user's question rather than faults of the
            # machinery: the section is wrong, or the implementation was asked
            # and did not deliver. Reported as the sentence each carries.
            pc.logging.error(str(result))
        elif isinstance(result, pc.runtime.SandboxUnavailable):
            # No sandbox to produce the route in is the same answer as an
            # implementation that was asked and could not run: the object has no
            # route, and the machine is why. Reported the way `pc cae` reports
            # it, with both remedies rather than a traceback.
            pc.logging.error(
                pc.cam.dysfunction_report(
                    name,
                    implementation or "the configured implementation",
                    result,
                    remedy=pc.cam.NO_RUNTIME_REMEDY,
                )
            )
        else:
            raise result
        failures.append((name, result))
    return results, failures


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
    selected, _, recursive = _request(params, "//")
    keyword = params.get("keyword", "")
    package = ctx.resolve_package_path(selected)

    from partcad.actions.package import search_packages
    from partcad.actions.shape import (
        search_assemblies,
        search_interfaces,
        search_parts,
        search_scenes,
        search_sketches,
    )

    search_fns = {
        "parts": search_parts,
        "sketches": search_sketches,
        "assemblies": search_assemblies,
        "scenes": search_scenes,
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
                # Interfaces expose their package as `.project`; parts, sketches,
                # assemblies and scenes carry a flat `.project_name` (matches the
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

    A file type may also be named by its full path, `sim-gazebo:world`, which is
    how one that no package *here* declares is reached -- an engine's own scene
    format lives in that engine's plugin package, and the object being exported
    belongs to somebody else's. That is checked against the package it names
    rather than against this set: the set answers "which types can I write", and
    a path is already an answer to it.
    """
    if fmt is None:
        return

    bare, package_path = pc.output.split_format(ctx.name, fmt)
    if package_path is not None:
        package_obj = ctx.get_project(package_path)
        if package_obj is None:
            raise JsonRpcError(
                USAGE_ERROR,
                "The package implementing the '%s' file type is not found: %s. "
                "Is it imported by this workspace?" % (bare, package_path),
            )
        declared = set()
        for section in pc.output.SECTIONS:
            declared.update(pc.output.format_names(package_obj.config_obj.get(section)))
        if bare not in declared:
            raise JsonRpcError(
                USAGE_ERROR,
                "The package '%s' declares no '%s' file type. It declares: %s"
                % (package_path, bare, ", ".join(sorted(declared)) or "none"),
            )
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
    """Render/export parts, assemblies, scenes, sketches, or interfaces to files.

    Backs both `pc export` (3D formats) and `pc render` (2D projections); the CLI
    passes the ``format`` and the ``label`` ("Export"/"Render"). ``output_dir``,
    when given, is resolved to an absolute path by the CLI so it lands in the
    user's working directory (the daemon runs elsewhere). ``options_package``
    names a further package whose ``export:``/``render:`` sections are read on
    top of the built-in ones, which is how a custom implementation declared in
    one package is used against the objects of another.

    ``view``, ``viewport_origin`` and ``viewport_up`` re-aim the projection for
    this one run. They resolve to the very parameters a ``render:`` file type
    configures, so the override lands on top of the configuration rather than
    beside it, and a file type that does not project never reads them.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    selected, object_name, recursive = _request(params)
    package = ctx.resolve_package_path(selected)
    package_obj = ctx.get_project(package)
    if not package_obj:
        pc.logging.error("Package %s is not found" % package)
        return None
    package = package_obj.name

    fmt = params.get("format")
    output_dir = params.get("output_dir")
    ignore_manufacturability = params.get("ignore_manufacturability", False)
    options_package = params.get("options_package")
    if options_package:
        options_package = ctx.resolve_package_path(options_package)
        if ctx.get_project(options_package) is None:
            raise JsonRpcError(USAGE_ERROR, "Options package %s is not found" % options_package)

    from partcad.render import resolve_viewport

    try:
        render_opts = resolve_viewport(
            params.get("view"),
            params.get("viewport_origin"),
            params.get("viewport_up"),
        )
    except ValueError as e:
        # A view nobody offers, or a vector that is not one: the request cannot
        # be made sense of, so nothing is rendered rather than something aimed
        # somewhere else.
        raise JsonRpcError(USAGE_ERROR, str(e)) from e

    from partcad.exception import AssemblyDocumentError
    from partcad.render_overlay import Overlay

    # "--with-ports"/"--with-interfaces"/"--with-all": draw the connection
    # metadata on top of the projection. Only 'pc render' offers them, and only
    # the 'render:' file types act on them (see Shape._output_request).
    overlay = Overlay.of(
        ports=params.get("with_ports", False),
        interfaces=params.get("with_interfaces", False),
        all=params.get("with_all", False),
    )

    with (
        pc.logging.Process(params.get("label", "Render"), package),
        _creating_dirs(ctx, params.get("create_dirs", False)),
    ):
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
                overlay,
                render_opts,
                recursive,
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
    overlay=None,
    render_opts=None,
    recursive=False,
):
    """The body of 'render_objects', once the request has been made sense of."""
    import asyncio

    if recursive:
        packages = [p["name"] for p in ctx.get_all_packages(parent_name=package, has_stuff=True)]
    else:
        packages = [package]

    if recursive and object_name is not None:
        # Only the packages that have such an object. A package of the subtree
        # that declares none was not asked to render one, and asking it anyway
        # ends the whole run: 'Project.render_async()' raises 'EmptyShapesError'
        # for a name it cannot resolve, so one package without a 'bolt' used to
        # cost every other package its render.
        targets = _targets(ctx, pc, packages, object_name, _object_kind(params))
        if not targets:
            _nowhere(pc, object_name, package)
            return
        packages = [target for target, _ in targets]

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
            overlay,
            render_opts,
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
    overlay=None,
    render_opts=None,
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
                    overlay=overlay,
                    render_opts=render_opts,
                )
            else:
                sketches, interfaces, parts, assemblies, scenes = [], [], [], [], []
                if params.get("sketch"):
                    sketches.append(object_in_package)
                elif params.get("interface"):
                    interfaces.append(object_in_package)
                elif params.get("assembly"):
                    assemblies.append(object_in_package)
                elif params.get("scene"):
                    scenes.append(object_in_package)
                else:
                    parts.append(object_in_package)
                prj = ctx.get_project(package)
                if prj is None:
                    # A package that does not resolve, reported as what it is.
                    # Without this the next line raises "'NoneType' object has
                    # no attribute 'render_async'", which names neither the
                    # package nor the request that asked for it. The way in is
                    # an object name that carries a package of its own -
                    # 'resolve_resource_path' above cuts the package out of it
                    # - so a mistyped or shell-mangled name arrives here rather
                    # than being rejected earlier.
                    raise JsonRpcError(USAGE_ERROR, "Package '%s' is not found" % package)
                await prj.render_async(
                    sketches=sketches,
                    interfaces=interfaces,
                    parts=parts,
                    assemblies=assemblies,
                    scenes=scenes,
                    format=fmt,
                    output_dir=output_dir,
                    options_package=options_package,
                    ignore_manufacturability=ignore_manufacturability,
                    overlay=overlay,
                    render_opts=render_opts,
                )

    results = await asyncio.gather(*[render_package(package) for package in packages], return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result


def convert_object(session, params):
    """Convert a part, sketch, assembly or scene to another format and update its type."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    kind = params.get("kind", "part")
    object_name = params["object_name"]
    target_format = params.get("target_format")
    output_dir = params.get("output_dir")
    dry_run = params.get("dry_run", False)

    # One object, and rewriting a declaration at that. The object arrives as
    # 'object_name' here rather than as 'object', so the check is given the
    # name under the key it reads.
    _refuse_recursion({"package": params.get("package"), "object": object_name})

    if kind in ("part", "assembly", "scene"):
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
    elif kind == "scene":
        from partcad.actions.scene import convert_scene_action

        action = convert_scene_action
        starting_msg = "Starting scene conversion: '%s' -> '%s', dry_run=%s" % (
            object_name,
            target_format,
            dry_run,
        )
        done_msg = "Scene conversion of '%s' completed." % object_name
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
    scenes = item_objs(project.scenes)
    software = item_objs(project.software)

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
            "scenes": scenes,
            "software": software,
            "broken": broken,
        },
    )
    info(session, {})
