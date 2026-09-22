#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Send a shape tree to the PartCAD IDE viewer.

'Shape.show()' and 'Interface.show()' both end here, and both send the same
thing: one object, as the tree of nodes it is, with the geometry at every node
tessellated into glTF (see 'shape_gltf'). A part is that tree one node deep, an
assembly is a node per thing it holds, an interface is a node per port; the
viewer is handed all of them the same way and has no per-kind case in it at all.

What is left here is the delivery, and one decision: whether the camera stays
where the user put it. Everything else about the tree - the hierarchy, the names,
the placements, the ports and the interfaces of every node - is the shape's own
account of itself, built by the code that builds it for every other purpose
('Shape.get_representation'), and is passed through untouched.

'partcad_ide_client' is imported lazily right here. It ships inside this
distribution - its source is the 'partcad-ide-client' component, symlinked in at
'src' - so 'pip install partcad' is enough and nothing installs it separately;
the import is still lazy because it is only ever needed when something is being
shown, and still guarded because a partial or corrupted install should degrade a
preview to a warning rather than fail the command that asked for it.
"""

import importlib

from . import logging as pc_logging

# The name of the shape shown last, so that re-showing the same one after an
# edit keeps the camera where the user put it instead of jumping.
_previously_displayed = None


def _client():
    """The lazily imported 'partcad_ide_client', or None if it will not import.

    Shipped in this distribution, so None here means a broken installation
    rather than a missing optional package.
    """
    try:
        return importlib.import_module("partcad_ide_client")
    except ImportError:
        return None


def context(ctx, name=None):
    """The context to build what is being shown in: the one given, or the global one.

    The fallback is for a caller that cannot pass one - a script, a notebook, the
    REPL - and it is the context 'globals.init()' set. Anything that has one passes
    it: the daemon may be serving several and passes the session's (see
    'partcad_service_json_rpc.core.operations'), and leaning on the global there is
    how showing a sketch from the IDE's Explorer came to answer "A context is
    required to tessellate a shape tree" from deep inside a tessellation.

    Says so here when there is neither, and returns None. A show is a side effect of
    browsing and must not fail the command that asked for it, so the caller gives up
    quietly - but "there is no context" is worth reading once, where it is true,
    rather than as whatever the first thing to need one happens to raise.
    """
    if ctx is not None:
        return ctx
    from .globals import _partcad_context

    if _partcad_context is None:
        pc_logging.error("Cannot show '%s': there is no PartCAD context to build it in" % (name or "the shape"))
    return _partcad_context


async def show(ctx, tree, name=None, kind=None, package=None):
    """Display one shape tree in the IDE's PartCAD Viewer.

    'tree' is the object as 'Shape.get_representation(ctx, "gltf")' returns it:
    nodes carrying tessellated geometry, their placements, and the ports and
    interfaces each declares.

    'package' names the package the shown object belongs to, so that the viewer
    can ask the daemon the questions its other tabs answer - the bill of
    materials, the assembly instructions, where to buy the parts - which take a
    package and a name, not a name on its own.

    Never raises: a show is a side effect of browsing a package, and neither a
    missing IDE nor a shape that will not tessellate should fail the command
    that asked for it.
    """
    global _previously_displayed

    client = _client()
    if client is None:
        pc_logging.warning(
            'Failed to load "partcad_ide_client", which ships inside PartCAD itself. '
            "Giving up on the connection to the PartCAD IDE; reinstall PartCAD to repair it."
        )
        return False

    try:
        if tree is None:
            pc_logging.warning("Nothing to show for '%s'" % (name or "the shape"))
            return False

        keep_camera = _previously_displayed == name
        _previously_displayed = name

        pc_logging.info('Visualizing in "PartCAD Viewer"...')
        client.show(tree, name=name, kind=kind, package=package, keep_camera=keep_camera)
        return True
    except client.ViewerNotAvailable as e:
        pc_logging.warning("%s" % e)
        pc_logging.warning("No PartCAD IDE with an open PartCAD Viewer detected.")
        return False
    except Exception as e:
        pc_logging.warning(e)
        pc_logging.warning("Failed to show '%s' in the PartCAD Viewer." % (name or "the shape"))
        return False
