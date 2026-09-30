#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The geometry the ports of an object are drawn with.

A port is a coordinate frame, which is why a viewer draws it as a triad. Most
ports are also drawn *with* something - the circle of a hole, the profile of a
rail - and that something is a sketch the declaration names ('sketch:' on a port,
see 'interface.py'). A frame says where a connection happens; the sketch says what
it happens across, which is what makes an opening in a part readable as one.

What a node carries about a port is the *reference* to that sketch and not its
geometry (see 'shape_ports.connection_metadata'): reading a declaration is a
lookup, building a sketch is not, and the layer a node carries is re-stamped every
time a payload is materialized. So the geometry is attached afterwards, here, by
whoever asks a shape for a representation of itself.

**One copy per sketch, not per port.** A bolt pattern is four ports drawn with one
circle, and an assembly is that many times over; the table is keyed by the
reference the ports already name, so what travels is one sketch however many ports
point at it. That is also what lets a renderer parse each one once and draw an
instance of it per port.

Nothing here knows about glTF: the sketches are attached in whatever form the
representation is being built in, and are converted along with everything else
(see 'shape_gltf' and 'wrappers/wrapper_gltf.py', whose walk looks for geometry
wherever it sits rather than only where a node's own is).
"""

from . import logging as pc_logging
from . import shape_envelope


def references(tree) -> list:
    """Every sketch the ports in 'tree' are drawn with, once each, in order found.

    A list rather than a set so that what is built - and what a reader of the log
    sees - does not depend on a hash seed.
    """
    found = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        for port in node.get(shape_envelope.KEY_PORTS) or []:
            reference = port.get("sketch") if isinstance(port, dict) else None
            if reference:
                found.setdefault(reference, None)
        for child in node.get(shape_envelope.KEY_ASSEMBLY) or []:
            walk(child)

    walk(tree)
    return list(found)


async def attach_async(ctx, tree):
    """'tree' with the sketches its ports are drawn with, on its root node.

    Returns a shallow copy of the root: the tree handed in may be the very object
    a cache is holding, and a cached payload is shared by everything that reads it.

    A reference that will not resolve or will not build costs that port its
    boundary and nothing else - its frame is still drawn, and a frame is the half
    that says where the connection is. Which is why this never raises: an object is
    still worth looking at when one of the sketches it points at is broken.
    """
    if not isinstance(tree, dict):
        return tree

    needed = references(tree)
    if not needed:
        return tree

    sketches = {}
    for reference in needed:
        try:
            sketch = ctx.get_sketch(reference)
        except Exception as e:
            pc_logging.debug("Failed to resolve the port sketch '%s': %s" % (reference, e))
            continue
        if sketch is None:
            pc_logging.debug("There is no sketch '%s' to draw a port with" % reference)
            continue
        try:
            node = await sketch.get_representation(ctx, shape_envelope.FORM_BREP)
        except Exception as e:
            pc_logging.warning("Failed to build the port sketch '%s': %s" % (reference, e))
            continue
        if node is not None:
            sketches[reference] = node

    if not sketches:
        return tree

    attached = dict(tree)
    attached[shape_envelope.KEY_SKETCHES] = sketches
    return attached
