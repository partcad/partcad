#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What colour a shape is drawn in.

A shape may say. ``properties: color:`` is ``"#RRGGBB"`` or ``"#RRGGBBAA"`` (see
'docs/source/config_parts.rst'), filled in by whatever built the shape: a URDF
reader naming a link's colour, a reader of an assembly file finding one in it,
or a package writing it down. A node of an assembly that states a colour
colours everything under it that states none, the way a colour is inherited
down an XCAF document: a sub-assembly painted red is red all the way down,
except for the one bolt in it that says otherwise.

A shape that says nothing is drawn in DEFAULT_COLOR.

A part's faces may each say more: the CMF section its payload carries after the
BREP (see 'cmf_section' and docs/design/cmf.md) gives a face the display colour
of its own set, which is the most specific thing anything says about it and
wins over what the part's node and the nodes above it say. A face its section
leaves uncoloured is drawn in the node's colour, as before.

Everything that draws a shape draws it in these colours, so that one part looks
like one part wherever it is looked at: the projections '//builtin/render'
writes - the SVG, and the PNG and JPEG drawn from it - and the IDE's Digital
Thread, in every pane of it that draws the shape in 3D. The Digital Thread is a
webview and cannot import Python, so it keeps a copy of DEFAULT_COLOR in
'ide/vscode/src/webview/appearance.ts', and a test holds the two to the same
colour.

A shape may also say it is one-sided (``properties: oneSided: true``, what a
wall reports): drawn from the front of its faces only, and see-through from
behind. Every drawing from a viewpoint takes the faces of such a shape that
turn their backs on the camera out before it projects ('split_for_view'), which
is how a room drawn from outside is drawn into through its near walls.

Everything here but 'split_by_color' and 'split_for_view' is plain Python, and
those reach OCP only when they are called - the first only through
'ocp_serialize' - so reading a colour does not load the kernel.
"""

import string

import ocp_serialize

# The colour OCCT draws a shape nobody coloured: 'Quantity_NOC_GOLDENROD', as
# the sRGB it is defined in. It is what an uncoloured shape looks like in OCCT's
# own viewer and in the viewers built on it, which makes it what a reader of a
# CAD drawing already expects a part to look like before anybody says what it
# is made of - and what PartCAD's own drawings were not, until they were drawn
# in it too. Upper case, because 'normalize' writes every colour that way and a
# stated "#daa520" is this colour and not another.
DEFAULT_COLOR = "#DAA520"

# Where a node of the shape tree says what it is. The twin of
# 'partcad.shape_envelope.KEY_PROPERTIES', spelled out here because a wrapper
# runs in a sandbox and cannot import 'partcad' (see 'wrapper_export.py', which
# names the same key 'PROPERTIES_KEY' for the same reason).
PROPERTIES_KEY = "properties"
COLOR_KEY = "color"
# A shape drawn from the front of its faces only, and see-through from behind:
# what a wall reports (see 'partcad.part_factory_wall', which names the same key
# 'ONE_SIDED_KEY', and the IDE's 'appearance.ts', which draws it the same way).
# Inherited down the tree like a colour, and independently of one.
ONE_SIDED_KEY = "oneSided"

# How far a face of a one-sided shape may turn away from the camera and still be
# drawn, as the cosine of the angle past edge-on: nought, give or take the
# arithmetic. A face seen exactly edge-on - every wall of a room seen from
# straight above - is kept, because that is what a floor plan is drawn with.
EDGE_ON = 1e-9


def parse(text):
    """A colour as '(red, green, blue, alpha)', or None if 'text' is not one.

    'text' is "#RRGGBB" or "#RRGGBBAA" in either case, and the '#' may be left
    out. The three channels come back as integers from 0 to 255, and alpha as a
    fraction from 0 (not there at all) to 1 (opaque), which is what it is when
    the colour does not say.

    Anything else is not a colour, and that includes a name: "red" is what a
    part's 'color' *parameter* may be, but never what its 'color' *property* is
    (see 'PartFactory.OBJECT_TYPE_PARAMETER_PROPERTIES'). It is answered with
    None rather than with a guess, so the caller says what it is ignoring.
    """
    if not isinstance(text, str):
        return None
    digits = text.strip()
    if digits.startswith("#"):
        digits = digits[1:]
    # 'int(..., 16)' is not a strict enough test on its own: it reads " f",
    # "+f" and "-1" too.
    if len(digits) not in (6, 8) or not all(digit in string.hexdigits for digit in digits):
        return None
    channels = [int(digits[i : i + 2], 16) for i in range(0, len(digits), 2)]
    alpha = channels[3] / 255.0 if len(channels) == 4 else 1.0
    return channels[0], channels[1], channels[2], alpha


def normalize(text):
    """A colour, written the one way it is written everywhere, or None.

    "#RRGGBB" in upper case, and "#RRGGBBAA" only when it is not opaque: two
    spellings of one colour are one colour, and a drawing that has a layer per
    colour must not have two for it.
    """
    parsed = parse(text)
    if parsed is None:
        return None
    red, green, blue, alpha = parsed
    color = "#%02X%02X%02X" % (red, green, blue)
    if alpha < 1.0:
        color += "%02X" % round(alpha * 255)
    return color


def stated(node):
    """The colour a node of the shape tree states, as it was written, or None."""
    if not isinstance(node, dict):
        return None
    properties = node.get(PROPERTIES_KEY)
    if not isinstance(properties, dict):
        return None
    return properties.get(COLOR_KEY)


def _own(node, warnings):
    """The colour 'node' itself states, normalized, or None if it states none.

    One that states something that is not a colour states none, and says so in
    'warnings' - once, however many times the node is placed: an assembly of a
    hundred such bolts has one thing wrong with it, not a hundred.
    """
    text = stated(node)
    if text is None or text == "":
        return None
    color = normalize(text)
    if color is None and warnings is not None:
        warning = "Ignoring the colour %r of %s, which is not #RRGGBB or #RRGGBBAA" % (
            text,
            node.get("name") or node.get("label") or "a shape",
        )
        if warning not in warnings:
            warnings.append(warning)
    return color


def _hex(rgba):
    """A CMF set's display, '(red, green, blue, alpha)', as 'normalize' writes a colour."""
    red, green, blue, alpha = rgba
    color = "#%02X%02X%02X" % (red, green, blue)
    if alpha < 1:
        color += "%02X" % round(alpha * 255)
    return color


def face_colors(node, memo=None):
    """The colour of each face of 'node' its CMF section states - None for a face it leaves uncoloured.

    None when the section addresses no face one by one: the part is then one
    colour, the one its node states. In 'TopExp::MapShapes' order, the order
    the section addresses faces in. A node that is a piece of a compound its
    payload holds (KEY_CHILD) is drawn in its node's colour: its section
    addresses the compound's faces, not its own.

    Reading the section decompresses the payload, so it is read only where the
    summary recorded with it (in the node's metadata, see
    'ocp_serialize.encode_shape') says it addresses faces one by one - which
    nearly nothing does, so a drawing costs what it cost before - and 'memo',
    keyed by the payload as 'ocp_serialize' shares a decoding, is what makes an
    assembly of one brick placed 731 times read it once.
    """
    if not ocp_serialize.is_shape_object(node) or node.get(ocp_serialize.KEY_CHILD) is not None:
        return None
    if not _addresses_faces(node):
        return None
    payload = node[ocp_serialize.KEY_BREP]
    key = payload if isinstance(payload, (str, bytes)) else bytes(payload)
    if memo is not None and key in memo:
        return memo[key]
    colors = section_face_colors(ocp_serialize.cmf_of_payload(payload))
    if memo is not None:
        memo[key] = colors
    return colors


def section_face_colors(section):
    """'[colour or None per face]' a CMF section gives the faces it addresses, or None if it colours none one by one.

    The one rule for a face's colour, for everything that draws one: its own
    set's display, else the part's own set's (see 'cmf_section.Section.face_set').
    """
    if section is None or not section.faces:
        return None
    colors = []
    for index in range(len(section.faces)):
        rgba = section.face_set(index).rgba
        colors.append(_hex(rgba) if rgba is not None else None)
    return colors if any(colors) else None


def _addresses_faces(node) -> bool:
    """Whether the CMF summary recorded with a node's geometry counts faces one by one."""
    metadata = node.get(ocp_serialize.KEY_METADATA)
    summary = metadata.get(ocp_serialize.METADATA_CMF) if isinstance(metadata, dict) else None
    if not isinstance(summary, dict):
        return False
    return any(isinstance(entry.get("faces"), int) for entry in summary.get("sets") or [] if isinstance(entry, dict))


def colors_of(tree, warnings=None, memo=None):
    """Every colour 'tree' is drawn in, each once, in the order they are met.

    Read off what each node says, and off the CMF section of each payload that
    has one, without decoding any geometry. A tree with no geometry in it at all
    is drawn in nothing.
    """
    found = []
    memo = {} if memo is None else memo

    def walk(node, inherited):
        color = _own(node, warnings) or inherited
        if ocp_serialize.is_shape_object(node):
            for face_color in face_colors(node, memo) or [color]:
                face_color = face_color or color
                if face_color not in found:
                    found.append(face_color)
        elif ocp_serialize.is_assembly_object(node):
            for child in node[ocp_serialize.KEY_ASSEMBLY]:
                walk(child, color)

    walk(tree, DEFAULT_COLOR)
    return found


def _stated_one_sided(node):
    """Whether 'node' says it is one-sided: True, False, or None for a node that says nothing."""
    if not isinstance(node, dict):
        return None
    properties = node.get(PROPERTIES_KEY)
    if not isinstance(properties, dict):
        return None
    value = properties.get(ONE_SIDED_KEY)
    return value if isinstance(value, bool) else None


def has_one_sided(tree):
    """Whether any shape in 'tree' is drawn one-sided, read off what the nodes say."""

    def walk(node, inherited):
        stated = _stated_one_sided(node)
        one_sided = inherited if stated is None else stated
        if ocp_serialize.is_shape_object(node):
            return one_sided
        if ocp_serialize.is_assembly_object(node):
            return any(walk(child, one_sided) for child in node[ocp_serialize.KEY_ASSEMBLY])
        return False

    return walk(tree, False)


def _placed_leaves(tree, memo):
    """Every piece of 'tree' a drawing draws, as '(colour, one_sided, shape)', placed where it is in the whole.

    A piece is a shape node's geometry, or - where its CMF section colours its
    faces one by one - the faces of it in one colour ('_pieces'), exactly as
    'split_by_color' gathers them. Each placed by its node's own location and
    every location above it, innermost first - which is what placing the
    compound of a node's children at the node's location does to each of them -
    so the pieces are the very shapes the whole was built of, placed the same
    way. Nothing is decoded again.
    """
    leaves = []

    def placed(shape, packed):
        if packed is None:
            return shape
        return shape.Located(ocp_serialize.toploc_from_packed(packed))

    def walk(node, color, one_sided, above):
        color = _own(node, None) or color
        stated = _stated_one_sided(node)
        one_sided = one_sided if stated is None else stated
        if ocp_serialize.is_shape_object(node):
            for face_color, piece in _pieces(node, color, memo):
                shape = placed(piece, node.get(ocp_serialize.KEY_LOCATION))
                for packed in reversed(above):
                    shape = shape.Moved(ocp_serialize.toploc_from_packed(packed))
                leaves.append((face_color, one_sided, shape))
        elif ocp_serialize.is_assembly_object(node):
            location = node.get(ocp_serialize.KEY_LOCATION)
            inner = above + [location] if location is not None else above
            for child in node[ocp_serialize.KEY_ASSEMBLY]:
                walk(child, color, one_sided, inner)

    walk(tree, DEFAULT_COLOR, False, [])
    return leaves


def _faces(shape):
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    found = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        found.append(TopoDS.Face_s(explorer.Current()))
        explorer.Next()
    return found


def _facing(face, towards):
    """How much 'face' faces the camera: its normal, the way the face is oriented, dotted with 'towards'.

    'towards' points from what is drawn back at the camera. Taken at the middle
    of the face's parameters, which may be in a hole of it and need not be: the
    surface is there either way, and the faces this is asked of - a plane, or a
    piece of a cylinder no wider than half of it (see '_silhouette_pieces') -
    look one way all over.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.TopAbs import TopAbs_REVERSED

    u_min, u_max, v_min, v_max = BRepTools.UVBounds_s(face)
    point = gp_Pnt()
    du = gp_Vec()
    dv = gp_Vec()
    BRepAdaptor_Surface(face).D1((u_min + u_max) / 2.0, (v_min + v_max) / 2.0, point, du, dv)
    normal = du.Crossed(dv)
    if normal.Magnitude() == 0.0:
        return 0.0
    normal.Normalize()
    if face.Orientation() == TopAbs_REVERSED:
        normal.Reverse()
    return normal.Dot(towards)


def _silhouette_pieces(face, towards):
    """A cylindrical 'face' cut along the lines where the camera sees it edge-on, as a list of faces.

    Those lines are where its normal is square to the line of sight: the two
    generators the plane through the axis, square to the line of sight, cuts the
    cylinder along. Each piece between them faces the camera all over or faces
    away all over, so it is drawn whole or not at all - and a cut there adds no
    line to the drawing, because the hidden-line algorithm draws the silhouette
    exactly there anyway. A face that is not part of a cylinder, or one looked
    at along its axis (every point of it edge-on), is its own one piece.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.gp import gp_Dir, gp_Pln, gp_Vec
    from OCP.TopTools import TopTools_ListOfShape

    surface = BRepAdaptor_Surface(face)
    if surface.GetType() != GeomAbs_Cylinder:
        return [face]
    axis = surface.Cylinder().Axis()
    along = gp_Vec(axis.Direction())
    across = towards - along * towards.Dot(along)
    if across.Magnitude() <= EDGE_ON:
        return [face]
    # Big enough to cut the face from one end to the other, whatever its size.
    size = 10.0 * (surface.Cylinder().Radius() + abs(surface.LastVParameter() - surface.FirstVParameter()) + 1.0)
    location = axis.Location().Translated(along * ((surface.FirstVParameter() + surface.LastVParameter()) / 2.0))
    cutter = BRepBuilderAPI_MakeFace(gp_Pln(location, gp_Dir(across)), -size, size, -size, size).Face()
    arguments = TopTools_ListOfShape()
    arguments.Append(face)
    tools = TopTools_ListOfShape()
    tools.Append(cutter)
    splitter = BRepAlgoAPI_Splitter()
    splitter.SetArguments(arguments)
    splitter.SetTools(tools)
    splitter.Build()
    if not splitter.IsDone():
        return [face]
    pieces = _faces(splitter.Shape())
    return pieces or [face]


def without_backs(shape, origin):
    """'shape' with every face that turns its back on a camera looking from 'origin' taken out.

    What drawing a one-sided shape from 'origin' means: the faces whose fronts
    the camera sees, and those it sees edge-on - a wall seen from directly above
    is its plan - are drawn, and the ones it sees from behind are not there at
    all. The drawing is orthographic, so 'origin' is a direction (see
    'render_svg.LOOK_AT') and every face is judged against the same one. A
    curved face is cut where it turns away first (see '_silhouette_pieces'), so
    the near half of a round wall goes and the far half stays.
    """
    from OCP.gp import gp_Vec

    towards = gp_Vec(*[float(component) for component in origin])
    if towards.Magnitude() == 0.0:
        return shape
    towards.Normalize()
    kept = []
    for face in _faces(shape):
        for piece in _silhouette_pieces(face, towards):
            if _facing(piece, towards) >= -EDGE_ON:
                kept.append(piece)
    return ocp_serialize.compound_of(kept)


def split_for_view(tree, whole, origin, warnings=None):
    """'(whole, groups)' to draw 'tree' from 'origin': 'split_by_color' with the backs of one-sided shapes taken out.

    A tree with nothing one-sided in it - every tree but a room - is drawn
    exactly as 'split_by_color' splits it, 'whole' and all, edge for edge. One
    that has a one-sided shape is gathered a leaf at a time, each leaf placed as
    it is in 'whole'; a one-sided leaf loses the faces the camera would see from
    behind ('without_backs'), and 'whole' is made again of what is left, so that
    what hides what is decided on what is drawn.

    A drawing in which nothing is left - a lone wall looked at from behind - is
    an error that says so, rather than an empty page or a complaint about having
    nothing to export: what was asked for is a view from the side the shape is
    not seen from.
    """
    if not has_one_sided(tree):
        return whole, split_by_color(tree, whole, warnings)
    memo = {}
    colors = colors_of(tree, warnings, memo)
    leaves = {color: [] for color in colors}
    drawn = []
    culled = False
    for color, one_sided, shape in _placed_leaves(tree, memo):
        if one_sided:
            kept = without_backs(shape, origin)
            culled = culled or len(_faces(kept)) < len(_faces(shape))
            shape = kept
        # 'setdefault', as in 'split_by_color': a section written for other
        # geometry is ignored, and the node's own colour is then one
        # 'colors_of' may not have met.
        leaves.setdefault(color, []).append(shape)
        drawn.append(shape)
    if culled and not any(_has_geometry(shape) for shape in drawn):
        raise ValueError(
            "nothing faces the camera: everything in the drawing is one-sided and is seen from behind, where it "
            "is see-through. Look at it from the other side - a wall faces -Y, which '--view front' looks along"
        )
    groups = [(color, ocp_serialize.compound_of(shapes)) for color, shapes in leaves.items() if shapes]
    return ocp_serialize.compound_of(drawn), groups


def _has_geometry(shape):
    """Whether 'shape' holds anything a drawing could draw: a face, or an edge."""
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer

    return TopExp_Explorer(shape, TopAbs_EDGE).More()


def split_by_color(tree, whole, warnings=None):
    """'whole', split by the colour each part of it is drawn in.

    'tree' is the shape tree an implementation is handed as 'shape_tree' - every
    shape node carrying its own geometry, decoded, under 'ocp_serialize.KEY_SHAPE'
    - and 'whole' the geometry it is handed as 'wrapped', which is that tree
    decoded into one shape. Returns '[(colour, shape), ...]', one entry per
    colour in the order 'colors_of' meets them, each shape placed where it is in
    'whole'.

    A tree drawn in one colour - which is nearly every tree, since nearly
    nothing states a colour - is 'whole' itself, as its one entry. That is
    deliberate rather than a shortcut: a drawing of it is then the same drawing
    it was before colours were read at all, edge for edge, which a drawing kept
    in a repository depends on.

    A tree in several colours is gathered a leaf at a time: each leaf's own
    geometry placed by its own location and every location above it, and the
    leaves of one colour gathered into one compound. Nothing is decoded again;
    the leaves are the very shapes 'whole' was built of, placed the same way.
    """
    memo = {}
    colors = colors_of(tree, warnings, memo)
    if len(colors) <= 1:
        return [(colors[0] if colors else DEFAULT_COLOR, whole)]

    leaves = {color: [] for color in colors}

    def placed(shape, packed):
        if packed is None:
            return shape
        return shape.Located(ocp_serialize.toploc_from_packed(packed))

    def walk(node, inherited, above):
        # Asked of each node a second time, without the warnings: 'colors_of'
        # has said everything there is to say about them.
        color = _own(node, None) or inherited
        if ocp_serialize.is_shape_object(node):
            # Placed at its own location as 'decode_shape' places it, and then
            # by every location above it, innermost first - which is what
            # placing the compound of a node's children at the node's location
            # does to each of them.
            for face_color, piece in _pieces(node, color, memo):
                shape = placed(piece, node.get(ocp_serialize.KEY_LOCATION))
                for packed in reversed(above):
                    shape = shape.Moved(ocp_serialize.toploc_from_packed(packed))
                # 'setdefault': a section written for other geometry is ignored
                # for the faces (see 'faces_by_color'), and the node's own
                # colour is then one 'colors_of' may not have met.
                leaves.setdefault(face_color, []).append(shape)
        elif ocp_serialize.is_assembly_object(node):
            location = node.get(ocp_serialize.KEY_LOCATION)
            inner = above + [location] if location is not None else above
            for child in node[ocp_serialize.KEY_ASSEMBLY]:
                walk(child, color, inner)

    walk(tree, DEFAULT_COLOR, [])
    return [(color, ocp_serialize.compound_of(shapes)) for color, shapes in leaves.items() if shapes]


def _pieces(node, color, memo):
    """'[(colour, shape), ...]': a shape node's geometry, by the colour each face of it is drawn in.

    The node's own geometry, whole, where its section colours no face of it one
    by one, which is nearly always; otherwise its faces gathered by colour, a
    compound per colour, each face where it is in the geometry. A face the
    section leaves uncoloured is in 'color', the node's.
    """
    return faces_by_color(node[ocp_serialize.KEY_SHAPE], face_colors(node, memo), color)


def faces_by_color(shape, colors, color):
    """'[(colour, shape), ...]': 'shape' whole in 'color' if 'colors' is None, else its faces gathered by colour.

    'colors' is what 'section_face_colors' answers; a face it leaves uncoloured
    is in 'color'. A list that is not as long as the shape has faces was written
    for other geometry, says nothing true of this one, and is ignored.
    """
    if colors is None:
        return [(color, shape)]
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, faces)
    if faces.Extent() != len(colors):
        # A section written for other geometry: it says nothing true of this one.
        return [(color, shape)]
    groups = {}
    for index in range(faces.Extent()):
        groups.setdefault(colors[index] or color, []).append(faces.FindKey(index + 1))
    # An edge that bounds no face - a wire beside the solid - has no face to
    # take a colour from, and would otherwise be left out of every group and so
    # out of the drawing: it is drawn in the node's own colour.
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    edge_faces = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, edge_faces)
    for index in range(1, edge_faces.Extent() + 1):
        if edge_faces.FindFromIndex(index).Extent() == 0:
            groups.setdefault(color, []).append(edge_faces.FindKey(index))
    return [(face_color, ocp_serialize.compound_of(members)) for face_color, members in groups.items()]
