#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A shape's CMF as the exports write it (docs/design/cmf.md, section 9, "Exports").

Every export implementation is handed the object twice (see 'wrapper_export'):
as 'wrapped', the geometry, and as 'shape_tree', the tree it was decoded from,
each shape node of which carries its payload - its BREP and the CMF section
after it (see 'cmf_section'). By the time an exporter is handed it, the section
is in PartCAD's own terms: the core converts what a source stated and completes
it with the part's own CMF as the part is read ('partcad.cmf.apply_declared'),
so a set's colour, material and finish are canonical references to
declarations, and its display is what a declaration says to draw it in.

What every exporter needs of that is here, once, so that a STEP file, a glTF, a
3MF and a URDF of one part say the same thing about each of its faces:

- 'leaves' walks the tree to its shape nodes, with the colour each is drawn in
  where its section colours nothing - its own 'properties: color:', else the
  nearest one above it, as 'appearance' inherits it for a drawing - and the
  placements above it; 'paired' walks 'wrapped' beside it, for a format written
  from the geometry as a whole;
- 'face_sets' and 'solid_sets' are a leaf's CMF, a set per face and per solid of
  its own geometry, in 'TopExp::MapShapes' order, the order the section
  addresses them in;
- 'groups' gathers a shape's faces by set, which is what a format with a
  material per primitive (glTF), per visual (URDF) or per triangle (3MF) makes
  of them;
- 'display_name' is what a set is called where a format names its materials;
- 'dropped' is the one warning a format that carries none of it gives.

A face nobody coloured is written uncoloured - the reading tool draws it in its
own default - rather than in the goldenrod PartCAD draws it in
('appearance.DEFAULT_COLOR'), which is a picture of "unspecified" and not a
colour anybody stated. The one exception is a mesh format that has to give every
triangle of a coloured object some property (3MF); it gives those the display
default, under the name UNSPECIFIED, which the 3MF reader reads back as nothing.

Plain Python until a function needs a shape's faces, and then OCP.
"""

import urllib.parse

import appearance
import cmf_section
import ocp_serialize

# What a 3MF calls the base material of the faces of a coloured object that
# nobody coloured: see the module docstring, and 'cmf_capture.read_mesh', which
# reads a triangle in it as uncoloured.
UNSPECIFIED = "unspecified"


class Leaf:
    """A shape node of the tree, with what it is drawn in and where it sits.

    'color' is the display colour it is drawn in where its section colours
    nothing ('#RRGGBB[AA]'), or None; 'above' the packed locations of the nodes
    above it, outermost first.
    """

    __slots__ = ("node", "color", "above")

    def __init__(self, node, color, above) -> None:
        self.node = node
        self.color = color
        self.above = list(above)

    @property
    def shape(self):
        """The node's own geometry, decoded, in its own frame."""
        return self.node[ocp_serialize.KEY_SHAPE]

    @property
    def definition(self):
        """The node's own geometry, unplaced: what 'face_sets' and 'solid_sets' count the faces and solids of."""
        from OCP.TopLoc import TopLoc_Location

        return self.shape.Located(TopLoc_Location())

    def location(self):
        """Where the node is in its parent, as 'ocp_serialize.decode_tree' puts it there.

        At its own location where it has one, which replaces whatever location
        its geometry carried; where it already was otherwise.
        """
        packed = self.node.get(ocp_serialize.KEY_LOCATION)
        return ocp_serialize.toploc_from_packed(packed) if packed is not None else self.shape.Location()

    def placed(self, shape=None):
        """'shape' (by default the node's unplaced geometry, or any of its faces) placed where it is in the whole.

        At the node's location, and then by every location above it, innermost
        first - which is what placing the compound of a node's children at the
        node's location does to each of them. The same place as the node's
        geometry in 'wrapped', and not the same location object: a
        'TopLoc_Location' made again is another location to OCCT, so a face
        placed here is never found among the faces of 'wrapped' (see 'paired').
        """
        shape = self.definition if shape is None else shape
        shape = shape.Located(self.location())
        for packed in reversed(self.above):
            shape = shape.Moved(ocp_serialize.toploc_from_packed(packed))
        return shape


def paired(tree, whole, warnings=None) -> list:
    """'[(leaf, shape), ...]': every leaf of 'tree' and its geometry as it is in 'whole', the very sub-shape.

    'whole' is 'wrapped', the tree decoded into one shape: a compound per
    assembly node, of its children in order, and each shape node's geometry
    placed (see 'ocp_serialize.decode_tree'). Walked beside the tree, so that a
    face of a leaf's geometry here is a face of 'whole' to OCCT - the same
    sub-shape, at the same location - which a leaf placed again ('Leaf.placed')
    is not. A tree 'whole' is not the decoding of is answered with nothing.
    """
    from OCP.TopoDS import TopoDS_Iterator

    found = []

    def walk(node, shape, inherited, above):
        if not isinstance(node, dict):
            return False
        color = appearance.own_color(node, warnings) or inherited
        if ocp_serialize.is_shape_object(node):
            if ocp_serialize.KEY_SHAPE in node:
                found.append((Leaf(node, color, above), shape))
            return True
        if not ocp_serialize.is_assembly_object(node):
            return False
        location = node.get(ocp_serialize.KEY_LOCATION)
        inner = above + [location] if location is not None else above
        children = [child for child in node[ocp_serialize.KEY_ASSEMBLY]]
        iterator = TopoDS_Iterator(shape)
        pieces = []
        while iterator.More():
            pieces.append(iterator.Value())
            iterator.Next()
        if len(pieces) != len(children):
            return False
        return all(walk(child, piece, color, inner) for child, piece in zip(children, pieces))

    if whole is None or not walk(tree, whole, None, []):
        return []
    return found


def leaves(tree, warnings=None) -> list:
    """Every shape node of 'tree' as a 'Leaf', in the order the tree holds them.

    'tree' is 'shape_tree' as an implementation is handed it: every shape node
    carries its decoded geometry under 'ocp_serialize.KEY_SHAPE'. A colour a
    node states that is not one is reported in 'warnings', once.
    """
    found = []

    def walk(node, inherited, above):
        if not isinstance(node, dict):
            return
        color = appearance.own_color(node, warnings) or inherited
        if ocp_serialize.is_shape_object(node):
            if ocp_serialize.KEY_SHAPE in node:
                found.append(Leaf(node, color, above))
        elif ocp_serialize.is_assembly_object(node):
            location = node.get(ocp_serialize.KEY_LOCATION)
            inner = above + [location] if location is not None else above
            for child in node[ocp_serialize.KEY_ASSEMBLY]:
                walk(child, color, inner)

    walk(tree, None, [])
    return found


def _summary(node):
    metadata = node.get(ocp_serialize.KEY_METADATA) if isinstance(node, dict) else None
    summary = metadata.get(ocp_serialize.METADATA_CMF) if isinstance(metadata, dict) else None
    return summary if isinstance(summary, dict) else None


def section_of(node, memo=None):
    """The CMF section a shape node's geometry is in, or None.

    Read only where the summary recorded with the node says there is one, so a
    tree with no CMF in it costs nothing; 'memo', keyed by the payload, is what
    makes a part placed a hundred times read once. A node that is a piece of a
    compound its payload holds ('ocp_serialize.KEY_CHILD') is in the part's own
    set: the section addresses the compound's faces and solids, not the piece's
    (docs/design/cmf.md, section 6).
    """
    if not ocp_serialize.is_shape_object(node):
        return None
    summary = _summary(node)
    if summary is None or not summary.get("sets"):
        return None
    payload = node[ocp_serialize.KEY_BREP]
    key = payload if isinstance(payload, (str, bytes)) else bytes(payload)
    if memo is not None and key in memo:
        section = memo[key]
    else:
        section = ocp_serialize.cmf_of_payload(payload)
        if memo is not None:
            memo[key] = section
    if section is not None and node.get(ocp_serialize.KEY_CHILD) is not None:
        own = section.own()
        return cmf_section.Section([own], 0) if own is not None else None
    return section


def with_display(cmf_set, color):
    """'cmf_set' drawn in 'color' ('#RRGGBB[AA]') where it says nothing of how it is drawn; it otherwise."""
    if cmf_set.rgba is not None or not color:
        return cmf_set
    rgba = appearance.parse(color)
    if rgba is None:
        return cmf_set
    return cmf_section.CmfSet(
        cmf_set.color,
        cmf_set.material,
        cmf_set.finish,
        cmf_set.origin,
        rgba,
        cmf_set.roughness,
        cmf_set.metallic,
    )


def _mapped(shape, kind):
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, found)
    return found


def _per(shape, kind, addressed, section, pick) -> list:
    """'pick(index)' for every sub-shape of 'kind' of 'shape', or the part's own set for each where 'addressed' is not of it."""
    count = _mapped(shape, kind).Extent()
    if addressed and len(addressed) != count:
        # Written for other geometry: what it says of each one is not true of
        # this one, and only the part's own set is.
        own = section.own() or cmf_section.CmfSet()
        return [own] * count
    return [pick(index) for index in range(count)]


def face_sets(leaf, memo=None, shape=None) -> list:
    """The set each face of a leaf's geometry is in, in 'TopExp::MapShapes' order.

    Its section's (see 'cmf_section.Section.face_set'), drawn in the leaf's
    colour where the section colours nothing. 'shape' is the leaf's unplaced
    geometry by default; any shape of the same faces in the same order will do
    (the geometry placed, a copy).
    """
    from OCP.TopAbs import TopAbs_FACE

    section = section_of(leaf.node, memo)
    shape = leaf.definition if shape is None else shape
    if section is None:
        sets = [cmf_section.CmfSet()] * _mapped(shape, TopAbs_FACE).Extent()
    else:
        sets = _per(shape, TopAbs_FACE, section.faces, section, section.face_set)
    return [with_display(cmf_set, leaf.color) for cmf_set in sets]


def solid_sets(leaf, memo=None, shape=None) -> list:
    """The set each solid of a leaf's geometry is in, in 'TopExp::MapShapes' order: what it is made of."""
    from OCP.TopAbs import TopAbs_SOLID

    section = section_of(leaf.node, memo)
    shape = leaf.definition if shape is None else shape
    if section is None:
        return [cmf_section.CmfSet()] * _mapped(shape, TopAbs_SOLID).Extent()
    return _per(shape, TopAbs_SOLID, section.solids, section, section.solid_set)


def is_plain(cmf_set) -> bool:
    """Whether a set says nothing a file could carry: no reference, and nothing to draw it in."""
    return cmf_set is None or (
        cmf_set.color is None and cmf_set.material is None and cmf_set.finish is None and cmf_set.rgba is None
    )


def appearance_key(cmf_set):
    """What a set looks like and is called: two sets alike in this are one material of a mesh format.

    The origin is not a part of it - two faces whose CMF came from different
    places and is the same CMF are one material.
    """
    if cmf_set is None:
        return None
    return (cmf_set.color, cmf_set.material, cmf_set.finish, cmf_set.rgba, cmf_set.roughness, cmf_set.metallic)


def groups(shape, sets) -> list:
    """'[(set, shape), ...]': 'shape' whole in its one set, or its faces gathered by set.

    'sets' is a set per face of 'shape', as 'face_sets' answers. One set - which
    nearly every part is - is 'shape' itself, so that what is written of it is
    what was written before CMF existed, triangle for triangle. Otherwise one
    compound of faces per set, in the order the faces first meet them; the faces
    are the shape's own, so whatever mesh they carry is kept.
    """
    from OCP.TopAbs import TopAbs_FACE

    keys = []
    by_key = {}
    for cmf_set in sets:
        key = appearance_key(cmf_set)
        if key not in by_key:
            by_key[key] = cmf_set
            keys.append(key)
    if len(keys) <= 1:
        return [(sets[0] if sets else cmf_section.CmfSet(), shape)]
    faces = _mapped(shape, TopAbs_FACE)
    if faces.Extent() != len(sets):
        return [(cmf_section.CmfSet(), shape)]
    members = {key: [] for key in keys}
    for index, cmf_set in enumerate(sets):
        members[appearance_key(cmf_set)].append(faces.FindKey(index + 1))
    return [(by_key[key], ocp_serialize.compound_of(members[key])) for key in keys]


def hex_of(rgba) -> str:
    """'(red, green, blue, alpha)' as '#RRGGBB', or '#RRGGBBAA' when it is not opaque."""
    red, green, blue, alpha = rgba
    text = "#%02X%02X%02X" % (red, green, blue)
    if alpha < 1:
        text += "%02X" % round(alpha * 255)
    return text


def hex_rgba(rgba) -> str:
    """'(red, green, blue, alpha)' as '#RRGGBBAA', always with its alpha: 3MF's 'displaycolor'."""
    red, green, blue, alpha = rgba
    return "#%02X%02X%02X%02X" % (red, green, blue, max(0, min(255, round(alpha * 255))))


def linear(channel) -> float:
    """One sRGB channel, 0 to 255, as the linear value from 0 to 1 a glTF factor holds (IEC 61966-2-1)."""
    value = channel / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


# What PartCAD's display-only colour is called: a reference to it is written as
# the colour it draws. A copy of 'partcad.cmf.RGBA', since this runs in a
# sandbox that cannot import the core; a test holds the two to each other.
_RGBA = "//builtin/color:rgba"


def reference_name(reference) -> str:
    """What a reference is called where a person reads it: its declaration's name, its parameters dropped.

    '//pkg:Medium Stone Grey' is 'Medium Stone Grey', '//pkg:PA12%2C glass
    filled' is 'PA12, glass filled', and the display-only '//builtin/color:rgba'
    of a colour is the colour, '#C91A09'.
    """
    text = str(reference)
    if text.startswith(_RGBA + ";"):
        for parameter in text[len(_RGBA) + 1 :].split(";"):
            name, _, value = parameter.partition("=")
            if name == "color" and len(value) in (6, 8):
                parsed = appearance.parse(value)
                if parsed is not None:
                    return hex_of(parsed)
    name = text.rpartition(":")[2].split(";")[0]
    return urllib.parse.unquote(name) or text


def display_name(cmf_set) -> str:
    """What a set is called where a format names a material: its colour, material and finish, in that order.

    'Signal Red / ABS / VDI 3400 Ref 27' - each by its declaration's name, as
    PartCAD shows CMF everywhere (docs/design/cmf.md, section 9). A set that
    names nothing is the colour it is drawn in, or UNSPECIFIED.
    """
    parts = [reference_name(reference) for reference in (cmf_set.color, cmf_set.material, cmf_set.finish) if reference]
    if parts:
        return " / ".join(parts)
    if cmf_set.rgba is not None:
        return hex_of(cmf_set.rgba)
    return UNSPECIFIED


def carries_cmf(tree) -> bool:
    """Whether anything in 'tree' states CMF: a node's 'properties: color:', or a set in a summary.

    Read off what the nodes say about themselves; no payload is opened.
    """
    found = False

    def walk(node):
        nonlocal found
        if found or not isinstance(node, dict):
            return
        if appearance.stated(node):
            found = True
            return
        summary = _summary(node)
        if summary is not None:
            for entry in summary.get("sets") or []:
                if isinstance(entry, dict) and any(
                    entry.get(key) for key in ("color", "material", "finish", "display")
                ):
                    found = True
                    return
        for child in node.get(ocp_serialize.KEY_ASSEMBLY) or []:
            walk(child)

    walk(tree)
    return found


def dropped(request, format_name: str):
    """The warning a file of a format that carries no CMF gives, once per file - or None when there is nothing to drop.

    An STL is triangles and nothing else, and so is what PartCAD writes as OBJ,
    three.js, IGES and BREP: the colour, material and finish of every face of
    the part are not in the file, and whoever opens it should be told rather
    than find out.
    """
    if not carries_cmf(request.get("shape_tree")):
        return None
    return (
        "%s carries no colour, material or finish: the CMF of %s is not in the file "
        "(export STEP, glTF or 3MF to keep it)" % (format_name, request.get("shape_name") or "the shape")
    )
