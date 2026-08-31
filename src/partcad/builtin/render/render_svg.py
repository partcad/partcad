#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in SVG renderer (see '//builtin/render' in partcad.yaml).

'render_png.py' and 'render_dxf.py' both start from what this produces, so they
import 'process()' from here rather than duplicating the projection.
"""

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize. Without this the
# standard library's pyexpat binds to VTK's older expat and any later
# xml.dom use (build123d 0.11 imports IPython, which does exactly that)
# dies with an undefined-symbol ImportError.
import pyexpat  # noqa: F401

import build123d as b3d

sys.path.append(os.path.dirname(__file__))
import ocp_serialize
import stroke_text
import wrapper_common

# Two points closer than this are the same point, as far as a drawn line goes.
TOLERANCE = 1e-9

# The colours the overlays "pc render --with-ports"/"--with-interfaces" are
# drawn in. Both have to read against the green the geometry is drawn in and
# against each other.
PORTS_COLOR = (32, 96, 224)
INTERFACES_COLOR = (216, 118, 24)

# How big the port markers and their labels are, as a fraction of the
# projection's largest dimension - so that they are the same size on the picture
# whatever the object is measured in. Overridable per package through the
# 'port_marker_size'/'port_label_size' parameters of the file type.
DEFAULT_MARKER_SIZE = 0.1
DEFAULT_LABEL_SIZE = 0.035

# How many decimal places every coordinate in the SVG is written to. Ten is what
# this renderer has always written, and it is what the checked-in drawings were
# produced with, so it stays the default; a package that would rather have a
# smaller file than a nanometre it has no use for lowers it.
DEFAULT_PRECISION = 10


def viewport_origin(request):
    """Where the shape is looked at from, when the request does not say.

    A sketch is flat, so it is looked at head-on; anything else is looked at
    from a corner, which is what makes a 3D shape read as 3D.
    """
    origin = request.get("viewport_origin")
    if origin:
        return tuple(origin)
    if request.get("shape_kind") == "sketch":
        return (0, 0, 100)
    return (100, -100, 100)


def viewport_up(request):
    """Which way is up in the projection, when the request does not say."""
    up = request.get("viewport_up")
    if up:
        return tuple(up)
    if request.get("shape_kind") == "sketch":
        return (0, 1, 0)
    return (0, 0, 1)


def precision(request):
    """How many decimal places the coordinates are written to."""
    value = request.get("precision")
    if value is None:
        return DEFAULT_PRECISION
    value = int(value)
    if value < 0:
        raise ValueError("'precision' must not be negative: %s" % value)
    return value


def _normalize_mesh(shape):
    """Round-trip a triangulation-only shape (e.g. an SDF mesh) through STL.

    Such a shape has no topological edges for 'project_to_viewport' to use;
    writing it to STL and reading it back yields a shape it can project. This
    runs inside the render runtime, so no OCCT mesh handling leaks into the main
    process, and the normalized shape never crosses a runtime boundary.
    """
    import tempfile
    from OCP.StlAPI import StlAPI_Writer, StlAPI_Reader
    from OCP.TopoDS import TopoDS_Shape

    fd, tmp_path = tempfile.mkstemp(suffix=".stl")
    os.close(fd)
    try:
        writer = StlAPI_Writer()
        if not writer.Write(shape, tmp_path):
            from OCP.BRepMesh import BRepMesh_IncrementalMesh

            BRepMesh_IncrementalMesh(shape, 0.1).Perform()
            writer.Write(shape, tmp_path)
        reader = StlAPI_Reader()
        result = TopoDS_Shape()
        if reader.Read(result, tmp_path) and not result.IsNull():
            return result
        return shape
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def needs_mesh_normalization(request):
    """SDF parts are meshes: a triangulation with no edges to project."""
    if request.get("normalize_mesh") is not None:
        return bool(request["normalize_mesh"])
    return request.get("shape_type") == "sdf"


def _annotation_edges(annotations):
    """The line segments to draw on top of the projection, as build123d edges.

    Each annotation is a pair of 3D points in the coordinate system of the shape
    being rendered. Segments too short to draw are dropped, with a tolerance
    rather than by exact equality: 'Edge.make_line' rejects two points that are
    merely very close, and an annotation is decoration - one that cannot be built
    must not cost the caller the projection it was going to be drawn on.
    """
    edges = []
    for annotation in annotations:
        start, end = tuple(annotation[0]), tuple(annotation[1])
        if all(abs(float(a) - float(b)) < TOLERANCE for a, b in zip(start, end)):
            continue
        try:
            edges.append(b3d.Edge.make_line(start, end))
        except Exception as e:
            sys.stderr.write("Skipping an annotation from %s to %s: %s\n" % (start, end, e))
    return edges


def _camera_axes(origin, up, look_at):
    """Which way is right and which way is up, in 3D, on the finished picture.

    Built exactly as 'project_to_viewport' builds it, out of the same three
    values, so that a label laid out along these two directions comes out square
    to the page rather than skewed with the object. (The construction is
    'gp_Ax2' - it is what orthogonalizes 'up' against the viewing direction, and
    what decides the handedness of the pair - so it is asked rather than
    reimplemented.)
    """
    from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt

    direction = (b3d.Vector(origin) - b3d.Vector(look_at)).normalized()
    camera = gp_Ax2()
    camera.SetAxis(gp_Ax1(gp_Pnt(*origin), gp_Dir(*direction.to_tuple())))
    camera.SetYDirection(gp_Dir(*b3d.Vector(up).normalized().to_tuple()))
    right, upward = camera.XDirection(), camera.YDirection()
    return (right.X(), right.Y(), right.Z()), (upward.X(), upward.Y(), upward.Z())


def _polyline_edges(points):
    """The line segments of one polyline, skipping the degenerate ones."""
    edges = []
    for start, end in zip(points, points[1:]):
        if all(abs(a - b) < TOLERANCE for a, b in zip(start, end)):
            continue
        try:
            edges.append(b3d.Edge.make_line(start, end))
        except Exception as e:
            sys.stderr.write("Skipping a segment from %s to %s: %s\n" % (start, end, e))
    return edges


def _transform_point(location, point):
    """'point', given in the frame of the packed 'location', in world coordinates."""
    from OCP.gp import gp_Pnt

    transformed = gp_Pnt(*point).Transformed(ocp_serialize.toploc_from_packed(location).Transformation())
    return (transformed.X(), transformed.Y(), transformed.Z())


def _marker_edges(location, size):
    """A port drawn as its own coordinate frame.

    The +Z axis is the one that matters - it is the direction a part travels
    along when it is connected through this port, and two mating ports face
    along opposite Zs - so it is the long one and the one with the arrowhead.
    X and Y are drawn shorter, to show which way the frame is rolled.
    """
    head = size * 0.22
    segments = [
        [(0, 0, 0), (size * 0.55, 0, 0)],
        [(0, 0, 0), (0, size * 0.55, 0)],
        [(0, 0, 0), (0, 0, size)],
        [(head * 0.5, 0, size - head), (0, 0, size), (-head * 0.5, 0, size - head)],
        [(0, head * 0.5, size - head), (0, 0, size), (0, -head * 0.5, size - head)],
    ]
    edges = []
    for polyline in segments:
        edges.extend(_polyline_edges([_transform_point(location, point) for point in polyline]))
    return edges


def _label_edges(text, anchor, height, right, up):
    """'text' written on the page, starting at the 3D point 'anchor'.

    The glyphs are line segments (see 'stroke_text' for why they are not an SVG
    '<text>' element): laid out in the plane of the picture, so they read the
    same whichever way the object is turned, and projected with everything else.
    """
    edges = []
    for polyline in stroke_text.polylines(text):
        points = [
            tuple(anchor[axis] + right[axis] * x * height + up[axis] * y * height for axis in range(3))
            for x, y in polyline
        ]
        edges.extend(_polyline_edges(points))
    return edges


def _spread(anchor, text, size, right, up, placed):
    """Move a label down the page until it is not written over another one.

    Ports coincide on a projection far more often than they coincide in space -
    the near and the far end of a through hole are one spot on the picture, and
    so are the two faces of a plate - and a port's name is long enough that two
    labels a good distance apart still overlap. So each one is compared against
    the ones already written, as the boxes they actually occupy, and pushed down
    a line at a time until it fits. 'placed' accumulates those boxes in the
    coordinates of the picture.
    """
    left = sum(anchor[axis] * right[axis] for axis in range(3))
    right_edge = left + stroke_text.width(text) * size
    down = sum(anchor[axis] * up[axis] for axis in range(3))
    step = size * 1.4
    shift = 0.0
    while any(
        left < other_right and right_edge > other_left and abs(down + shift - other_down) < step * 0.9
        for other_left, other_right, other_down in placed
    ):
        shift -= step
    placed.append((left, right_edge, down + shift))
    return tuple(anchor[axis] + up[axis] * shift for axis in range(3))


def _interface_label(port):
    """How one port's interface is named on the picture.

    The interface, the instance of it this port belongs to, and - inside an
    assembly - the child that carries it: exactly the three things a 'connect:'
    has to name to pick this connection out of every other.
    """
    label = port["interface_label"]
    if port.get("instance"):
        label += "/" + port["instance"]
    if port.get("owner"):
        label = port["owner"] + ":" + label
    return label


def _overlay_edges(request, max_dimension, right, up):
    """The two overlays "pc render" can be asked to draw, as (layer, edges) pairs.

    'request["ports"]' is what 'partcad.render_overlay' worked out: every port of
    the object - and, for an assembly, of everything inside it - with the name a
    user would have to write in an ASSY file and the placement it ended up at.

    The two overlays answer two different questions, so they are drawn
    differently. "Where is this port and which way does it face" is one marker
    and one name per port. "Which ports make up this interface" is one name per
    *instance* of an interface, with a line out to each of the ports that belong
    to it - a bolt pattern of four holes is one thing a part connects through,
    and writing its name four times would say less, not more.
    """
    ports = request.get("ports") or []
    marker_size = float(request.get("port_marker_size", DEFAULT_MARKER_SIZE)) * max_dimension
    label_size = float(request.get("port_label_size", DEFAULT_LABEL_SIZE)) * max_dimension
    with_ports = bool(request.get("with_ports"))
    with_interfaces = bool(request.get("with_interfaces"))

    port_edges = []
    interface_edges = []
    instances = {}
    # Shared by both overlays, so that an interface name does not land on a port
    # name either.
    written = []
    for port in ports:
        location = port.get("location")
        if location is None:
            continue
        # A label hangs off the tip of the port's +Z arrow, which spreads the
        # labels the way the ports themselves are spread rather than piling them
        # all up on one face of the object.
        origin = _transform_point(location, (0, 0, 0))
        tip = _transform_point(location, (0, 0, marker_size * 1.15))
        if with_ports:
            port_edges.extend(_marker_edges(location, marker_size))
            text = port.get("port") or ""
            at = _spread(tip, text, label_size, right, up, written)
            port_edges.extend(_label_edges(text, at, label_size, right, up))
        if with_interfaces and port.get("interface_label"):
            instances.setdefault(_interface_label(port), []).append((origin, tip))

    for label, placed in instances.items():
        centre = tuple(sum(tip[axis] for _origin, tip in placed) / len(placed) for axis in range(3))
        anchor = _spread(centre, label, label_size, right, up, written)
        interface_edges.extend(_label_edges(label, anchor, label_size, right, up))
        # Which ports the name is the name of. A bolt pattern is only
        # recognizable as one interface if the four holes are joined up, and a
        # name with nothing joining it to anything names nothing in particular.
        for origin, _tip in placed:
            interface_edges.extend(_polyline_edges([anchor, origin]))

    return [
        ("Ports", PORTS_COLOR, port_edges),
        ("Interfaces", INTERFACES_COLOR, interface_edges),
    ]


def _interface_shapes(request):
    """The port boundaries to draw for "--with-interfaces", as live geometry.

    A port may declare the sketch that bounds it - the circle of a hole, the
    profile of a rail - and 'render_overlay' places a copy of it on every port
    that has one. They arrive already decoded (the export wrapper decodes the
    whole request), which is why they are shapes here and points everywhere else
    in this module.
    """
    if not request.get("with_interfaces"):
        return []
    shapes = []

    def collect(obj):
        """Add every decoded shape under 'obj', which may be a list of them."""
        if isinstance(obj, list):
            for item in obj:
                collect(item)
        elif obj is not None and not isinstance(obj, (dict, str, bytes, int, float, bool)):
            # Anything else is geometry. A dict here would mean the request was
            # not decoded, which a 'render:' file type never asks for - but a
            # sketch that failed to build leaves a null behind, and that is
            # ordinary.
            shapes.append(obj)

    for port in request.get("ports") or []:
        collect(port.get("sketch"))
    return shapes


def _add_projected(exporter, layer, shapes, origin, up, look_at):
    """Project 'shapes' the way the object itself was projected, and draw them.

    The same three viewing parameters, so that what is drawn on top of the
    object lands where the thing it describes is. They go through a projection
    of their own only so that they can be drawn in their own colour - and so
    that the object does not hide them: a port on the far side of a part is
    still a port worth seeing.

    'shapes' mixes build123d edges built here with the raw OCCT shapes the port
    boundaries arrive as, so they are compounded through OCCT rather than
    through 'Compound(children=...)', which takes only the former.
    """
    if not shapes:
        return
    try:
        compound = b3d.Solid.make_box(1, 1, 1)
        compound.wrapped = ocp_serialize.compound_of(
            shape.wrapped if hasattr(shape, "wrapped") else shape for shape in shapes
        )
        projected = compound.project_to_viewport(
            viewport_origin=origin,
            viewport_up=up,
            look_at=look_at,
        )[0]
        exporter.add_shape(projected, layer=layer)
    except Exception as e:
        wrapper_common.handle_exception(e)


def process(path, request):
    try:
        wrapped = request["wrapped"]
        if needs_mesh_normalization(request):
            wrapped = _normalize_mesh(wrapped)

        b3d_obj = b3d.Solid.make_box(1, 1, 1)
        b3d_obj.wrapped = wrapped

        origin = viewport_origin(request)
        up = viewport_up(request)
        # What 'project_to_viewport' would pick for itself, made explicit. It is
        # part of the projection - the viewing direction runs from the origin to
        # it - so anything projected separately and drawn on top has to be given
        # the same one or it lands somewhere else on the page.
        look_at = b3d_obj.center().to_tuple()
        visible, _hidden = b3d_obj.project_to_viewport(
            viewport_origin=origin,
            viewport_up=up,
            look_at=look_at,
        )
        max_dimension = max(*b3d.Compound(children=visible).bounding_box().size)
        if max_dimension == 0:
            max_dimension = 4
        scale = 512.0 / max_dimension
        exporter = b3d.ExportSVG(
            scale=scale,
            precision=precision(request),
        )
        line_weight = request.get("line_weight", 1.0)
        exporter.add_layer(
            "Visible",
            line_color=(64, 192, 64),
            line_weight=line_weight,
        )
        # A projection that cannot be added still leaves an SVG behind - an empty
        # one. That predates this package and is deliberately kept, because it is
        # what the shapes that hit it currently produce; what is new is that the
        # reason no longer disappears silently (it was a bare 'except: pass', so
        # it also swallowed KeyboardInterrupt).
        try:
            exporter.add_shape(visible, layer="Visible")
        except Exception as e:
            wrapper_common.handle_exception(e)

        # The annotations go through the very same projection, so that a line
        # pointing at a feature of the shape still points at it once both are
        # flattened. They are projected separately only so that they can be
        # drawn in their own style.
        annotations = request.get("annotations") or []
        edges = _annotation_edges(annotations)
        if edges:
            exporter.add_layer(
                "Annotations",
                line_color=(192, 64, 64),
                line_weight=line_weight,
                line_type=b3d.LineType.ISO_DASH,
            )
            _add_projected(exporter, "Annotations", edges, origin, up, look_at)

        # The ports and the interfaces, when they were asked for. Drawing them
        # cannot cost the picture: an overlay that fails is reported and the
        # projection is still written.
        if request.get("with_ports") or request.get("with_interfaces"):
            try:
                right, upward = _camera_axes(origin, up, look_at)
                overlays = _overlay_edges(request, max_dimension, right, upward)
                shapes = {"Interfaces": _interface_shapes(request)}
                for layer, color, layer_edges in overlays:
                    layer_shapes = layer_edges + shapes.get(layer, [])
                    if not layer_shapes:
                        continue
                    exporter.add_layer(layer, line_color=color, line_weight=line_weight)
                    _add_projected(exporter, layer, layer_shapes, origin, up, look_at)
            except Exception as e:
                wrapper_common.handle_exception(e)

        exporter.write(path)

        return {"success": True, "exception": None}
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
