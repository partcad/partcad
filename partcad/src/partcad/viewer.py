#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Send shapes to the PartCAD IDE viewer.

'Shape.show()' and 'Interface.show()' both end here. The work splits in two:

  * Tessellation runs in a sandbox (wrapper_show.py). The core carries shapes as
    BREP envelopes and never holds a live OCP object, so it cannot tessellate;
    and the receiving end is a browser, which cannot either. What crosses the
    socket is therefore compressed binary glTF.

  * Delivery runs through 'partcad_ide_client', imported lazily right here.
    That package ships inside this distribution (partcad/src/partcad_ide_client),
    so 'pip install partcad' is enough and nothing installs it separately; the
    import is still lazy because it is only ever needed when something is being
    shown, and still guarded because a partial or corrupted install should
    degrade a preview to a warning rather than fail the command that asked for
    it.

This replaces handing live OCP objects to 'ocp_vscode', which required a full
CAD stack in-process (and a second, differently-provisioned one in the IDE's
interpreter) purely to draw a picture.
"""

import importlib

from . import logging as pc_logging
from . import sandbox_versions
from . import shape_envelope
from . import wrapper

# The tessellation the viewer gets. Coarser than a render's default would be
# worth: this is an interactive preview that has to cross a socket and load in a
# webview, not an export.
DEFAULT_TOLERANCE = 0.1
DEFAULT_ANGULAR_TOLERANCE = 0.2

# export_gltf is build123d's; cadquery-ocp comes last because build123d pulls
# the VTK-less 'cadquery-ocp-novtk' build over it (see sandbox_versions).
_DEPENDENCIES = (sandbox_versions.BUILD123D, sandbox_versions.CADQUERY_OCP)

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


def _metadata_of(component, key):
    """The 'name' or 'label' a component carries, looking into a list's first entry."""
    if isinstance(component, (list, tuple)):
        component = component[0] if component else None
    return component.get(key) if isinstance(component, dict) else None


async def tessellate(ctx, components, name=None, tolerance=None, angular_tolerance=None):
    """Turn a component tree of BREP envelopes into displayable glTF objects.

    Returns the list of '{"name", "label", "gltf"}' objects the IDE protocol
    carries; the glTF is already compressed and base64-encoded by the wrapper.
    """
    if ctx is None:
        raise ValueError("A context is required to tessellate a shape for the viewer")

    runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
    # Installed one at a time, not concurrently: the order matters because
    # build123d overwrites the OCP native module cadquery-ocp installs.
    for dep in _DEPENDENCIES:
        await runtime.ensure_async(dep)

    components = list(components)
    request = {
        "components": components,
        # The sandbox's codec rebuilds live geometry from the envelopes and so
        # drops their metadata; carry it separately, positionally.
        "names": [_metadata_of(component, "name") for component in components],
        "labels": [_metadata_of(component, "label") for component in components],
        "name": name,
        "tolerance": DEFAULT_TOLERANCE if tolerance is None else tolerance,
        "angularTolerance": DEFAULT_ANGULAR_TOLERANCE if angular_tolerance is None else angular_tolerance,
    }

    # argv[1] is mandatory for every wrapper (wrapper_common.handle_input reads
    # it as the output path). A show has no output file - the glTF comes back
    # over the pipe - so it carries the operation name, which is what shows up
    # in process listings and logs.
    exitcode, response_serialized, errors = await runtime.run_async(
        [wrapper.get("show.py"), "show"],
        shape_envelope.serialize(request),
    )
    if exitcode != 0 and not errors:
        errors = "Failed to tessellate the shape for the viewer (exit code %s)" % exitcode
    if errors:
        raise Exception(errors)

    result = shape_envelope.deserialize(response_serialized)
    if not result.get("success", False):
        raise Exception(result.get("exception") or "Failed to tessellate the shape for the viewer")
    return result.get("objects") or []


async def show(ctx, components, name=None, kind=None, markers=None):
    """Tessellate 'components' and display them in the IDE's PartCAD Viewer.

    'markers' are bare coordinate frames with no geometry of their own - an
    interface's ports - carried as packed [[tx,ty,tz], [ax,ay,az], angle]
    locations for the viewer to draw axes at.

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
        # An interface whose ports carry no sketch has markers and nothing else;
        # do not spin up a sandbox just to tessellate an empty list.
        objects = await tessellate(ctx, components, name=name) if components else []
        if not objects and not markers:
            pc_logging.warning("Nothing to show for '%s'" % (name or "the shape"))
            return False

        keep_camera = _previously_displayed == name
        _previously_displayed = name

        pc_logging.info('Visualizing in "PartCAD Viewer"...')
        client.show(
            objects,
            name=name,
            kind=kind,
            keep_camera=keep_camera,
            markers=list(markers or []),
        )
        return True
    except client.ViewerNotAvailable as e:
        pc_logging.warning("%s" % e)
        pc_logging.warning("No PartCAD IDE with an open PartCAD Viewer detected.")
        return False
    except Exception as e:
        pc_logging.warning(e)
        pc_logging.warning("Failed to show '%s' in the PartCAD Viewer." % (name or "the shape"))
        return False
