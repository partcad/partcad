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

Everything that draws a shape draws it in these colours, so that one part looks
like one part wherever it is looked at: the projections '//builtin/render'
writes - the SVG, and the PNG and JPEG drawn from it - and the IDE's Digital
Thread, in every pane of it that draws the shape in 3D. The Digital Thread is a
webview and cannot import Python, so it keeps a copy of DEFAULT_COLOR in
'ide/vscode/src/webview/appearance.ts', and a test holds the two to the same
colour.

Everything here but 'split_by_color' is plain Python, and that one reaches OCP
only through 'ocp_serialize' and only when it is called, so reading a colour
does not load the kernel.
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


def colors_of(tree, warnings=None):
    """Every colour 'tree' is drawn in, each once, in the order they are met.

    Read off what each node says, without touching any geometry, so asking costs
    nothing. A tree with no geometry in it at all is drawn in nothing.
    """
    found = []

    def walk(node, inherited):
        color = _own(node, warnings) or inherited
        if ocp_serialize.is_shape_object(node):
            if color not in found:
                found.append(color)
        elif ocp_serialize.is_assembly_object(node):
            for child in node[ocp_serialize.KEY_ASSEMBLY]:
                walk(child, color)

    walk(tree, DEFAULT_COLOR)
    return found


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
    colors = colors_of(tree, warnings)
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
            shape = placed(node[ocp_serialize.KEY_SHAPE], node.get(ocp_serialize.KEY_LOCATION))
            for packed in reversed(above):
                shape = shape.Moved(ocp_serialize.toploc_from_packed(packed))
            leaves[color].append(shape)
        elif ocp_serialize.is_assembly_object(node):
            location = node.get(ocp_serialize.KEY_LOCATION)
            inner = above + [location] if location is not None else above
            for child in node[ocp_serialize.KEY_ASSEMBLY]:
                walk(child, color, inner)

    walk(tree, DEFAULT_COLOR, [])
    return [(color, ocp_serialize.compound_of(leaves[color])) for color in colors]
