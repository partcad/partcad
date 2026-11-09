#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a part's script says about its colours, materials and finishes (docs/design/cmf.md, section 7).

A script can say it two ways, and both are kept:

- in its CAD library's own terms - build123d's '.color' and '.material' on a
  shape and on the children of a compound, CadQuery's 'cq.Assembly' colours and
  the 'color' option of 'show_object' - which are a picture and a name, and are
  converted by the core like any other tool's (the 'build123d' and 'cadquery'
  conventions; see 'partcad.cmf_conventions');
- in PartCAD's own, with 'set_cmf(shape, color=..., material=..., finish=...)',
  which every part script is handed beside 'show_object' and which names CMF
  declarations as a 'partcad.yaml' does (':red', '//pub/...:pla').

Whatever is said is noted against the very shapes it is said of, and turned
into the part's CMF section once the part is put together ('section_for'):
matched by the shape, wherever the part puts it, and with the more specific
winning - a face's own over its solid's, a child's over the compound's, each
component on its own, as build123d and CadQuery themselves resolve it.

Imports nothing from OCP until it is asked for a section, so the script runner
can hand out 'set_cmf' without loading the kernel.
"""

PARTCAD = "raw:partcad"

# What 'set_cmf' and the libraries' own attributes noted, as
# '(shape, cmf_section.CmfSet, depth)': the shape it was said of, what was said,
# and how deep in what the script showed it was said. One list per process,
# which is one part: a wrapper builds one script.
_noted = []


def reset():
    del _noted[:]


def _wrapped(shape):
    """The OCCT shape behind whatever a script holds: build123d's and CadQuery's both say '.wrapped'."""
    for attribute in ("wrapped",):
        inner = getattr(shape, attribute, None)
        if inner is not None:
            return inner
    if hasattr(shape, "val"):
        return _wrapped(shape.val())
    return shape


def _values(obj) -> list:
    """Every shape a CadQuery object holds: each value of a 'Workplane', or the object itself."""
    if hasattr(obj, "vals"):
        try:
            return list(obj.vals())
        except Exception:  # pylint: disable=broad-except
            pass
    return [obj]


def _note(shape, cmf_set, depth=0):
    import cmf_section  # noqa: F401 - the set is one of its

    if shape is None or cmf_set is None:
        return
    _noted.append((shape, cmf_set, depth))


def set_cmf(shape, color=None, material=None, finish=None):
    """Say what 'shape' - the part, a solid of it, a face - is in, as CMF declarations; returns 'shape'.

    Each is a reference to a declaration, as a 'partcad.yaml' writes one: ':red'
    for one of the part's own package, '//pub/std/manufacturing/material/plastic:pla'
    for another's. Said of a solid, a colour is every face of it that says
    none of its own; said of a face, a material is not a material (materials
    are per solid), and is said of the solid the face bounds instead.
    """
    import cmf_section

    if color is None and material is None and finish is None:
        return shape
    _note(
        _wrapped(shape),
        cmf_section.CmfSet(color=color, material=material, finish=finish, origin=PARTCAD),
        # Said outright: deeper than anything a library attribute says.
        depth=1 << 16,
    )
    return shape


def _rgba(values):
    red, green, blue = (max(0, min(255, int(round(float(channel) * 255)))) for channel in values[:3])
    alpha = float(values[3]) if len(values) > 3 else 1.0
    return "#%02X%02X%02X" % (red, green, blue), (red, green, blue, alpha)


def _color_values(color):
    """'(red, green, blue, alpha)' from 0 to 1 of a build123d or CadQuery colour, or None."""
    if color is None:
        return None
    for method in ("to_tuple", "toTuple"):
        if hasattr(color, method):
            try:
                return tuple(getattr(color, method)())
            except Exception:  # pylint: disable=broad-except
                pass
    rgba = getattr(color, "wrapped", None)
    if rgba is not None and hasattr(rgba, "GetRGB"):
        rgb = rgba.GetRGB()
        return (rgb.Red(), rgb.Green(), rgb.Blue(), rgba.Alpha())
    if isinstance(color, (tuple, list)) and len(color) >= 3:
        values = [float(channel) for channel in color]
        if max(values[:3]) > 1:
            values[:3] = [channel / 255.0 for channel in values[:3]]
        return tuple(values)
    return None


def note_build123d(obj, depth=0, origin="raw:build123d"):
    """Note what a build123d object and its children say: '.color', '.material'.

    'origin' names the convention it is stated in: build123d's for a script's
    own objects, and the file's for what build123d read out of one (a 3MF's
    base materials, see 'wrapper_import_mesh').
    """
    import cmf_section

    wrapped = getattr(obj, "wrapped", None)
    if wrapped is None:
        return
    values = _color_values(getattr(obj, "color", None))
    material = getattr(obj, "material", None)
    material = material.strip() if isinstance(material, str) and material.strip() else None
    if values is not None or material is not None:
        designation, rgba = _rgba(values) if values is not None else (None, None)
        _note(
            wrapped,
            cmf_section.CmfSet(color=designation, rgba=rgba, material=material, origin=origin),
            depth,
        )
    for child in getattr(obj, "children", None) or ():
        note_build123d(child, depth + 1, origin)


def note_cadquery(obj, options=None, depth=0):
    """Note what a CadQuery result says: a 'cq.Assembly''s colours, and 'show_object''s 'color' option."""
    import cmf_section

    options = options or {}
    color = options.get("color")
    if color is not None:
        values = _color_values(color)
        if values is None and isinstance(color, str):
            values = _named_cadquery_color(color)
        if values is not None:
            if "alpha" in options and len(values) == 3:
                values = tuple(values) + (float(options["alpha"]),)
            designation, rgba = _rgba(values)
            cmf_set = cmf_section.CmfSet(color=designation, rgba=rgba, origin="raw:cadquery")
            for value in _values(obj):
                _note(_wrapped(value), cmf_set, depth)
    # A cq.Assembly: each child's colour, of the child's own shapes - all of
    # them, as its compound holds every value of a 'Workplane'.
    if hasattr(obj, "children") and hasattr(obj, "obj") and hasattr(obj, "color"):
        own = getattr(obj, "obj", None)
        values = _color_values(getattr(obj, "color", None))
        if own is not None and values is not None:
            designation, rgba = _rgba(values)
            cmf_set = cmf_section.CmfSet(color=designation, rgba=rgba, origin="raw:cadquery")
            for value in _values(own):
                _note(_wrapped(value), cmf_set, depth)
        for child in obj.children:
            note_cadquery(child, None, depth + 1)


def _named_cadquery_color(name):
    try:
        import cadquery as cq

        return tuple(cq.Color(name).toTuple())
    except Exception:  # pylint: disable=broad-except
        return None


def section_for(shape):
    """The CMF section of 'shape', the part as it was put together, from what was noted; None if nothing was.

    A shape that was noted is found in 'shape' as itself wherever the part put
    it: matched by what it is (its 'TShape'), not by where it is, because a
    script places what it shows. What is noted of a compound, a shell or a
    solid is said of every solid and face in it, and outer first, so that what
    is said of a part of it wins, component by component.
    """
    if not _noted:
        return None
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopTools import TopTools_IndexedMapOfShape

    import ocp_serialize

    def mapped(of, kind):
        found = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(of, kind, found)
        return found

    faces = mapped(shape, TopAbs_FACE)
    solids = mapped(shape, TopAbs_SOLID)

    def by_definition(found):
        definitions = TopTools_IndexedMapOfShape()
        places = []
        for index in range(1, found.Extent() + 1):
            definition = found.FindKey(index).Located(TopLoc_Location())
            if not definitions.Contains(definition):
                definitions.Add(definition)
                places.append([])
            places[definitions.FindIndex(definition) - 1].append(index)
        return definitions, places

    face_definitions, face_places = by_definition(faces)
    solid_definitions, solid_places = by_definition(solids)

    def where(of, kind, definitions, places):
        indices = []
        under = mapped(of, kind)
        for index in range(1, under.Extent() + 1):
            definition = under.FindKey(index).Located(TopLoc_Location())
            if definitions.Contains(definition):
                indices.extend(places[definitions.FindIndex(definition) - 1])
        return indices

    face_sets, solid_sets = {}, {}

    def say(table, index, cmf_set):
        table[index] = cmf_set.filled_from(table[index]) if index in table else cmf_set

    for noted, cmf_set, _depth in sorted(_noted, key=lambda entry: entry[2]):
        kind = noted.ShapeType().name if hasattr(noted, "ShapeType") else ""
        if kind == "TopAbs_FACE":
            # A face has a colour and a finish; its material is its solid's.
            for index in where(noted, TopAbs_FACE, face_definitions, face_places):
                say(face_sets, index, cmf_set.without(("material",)))
            if cmf_set.material is not None:
                material = cmf_set.without(("color", "finish"))
                for index in range(1, solids.Extent() + 1):
                    if where(noted, TopAbs_FACE, *by_definition(mapped(solids.FindKey(index), TopAbs_FACE))):
                        say(solid_sets, index, material)
            continue
        in_solids = where(noted, TopAbs_SOLID, solid_definitions, solid_places)
        for index in in_solids:
            say(solid_sets, index, cmf_set)
        if not in_solids:
            # A shell, or a compound of faces: colours its faces.
            for index in where(noted, TopAbs_FACE, face_definitions, face_places):
                say(face_sets, index, cmf_set.without(("material",)))

    if not face_sets and not solid_sets:
        return None
    return ocp_serialize.cmf_section_for(
        shape,
        faces={faces.FindKey(index): cmf_set for index, cmf_set in face_sets.items()},
        solids={solids.FindKey(index): cmf_set for index, cmf_set in solid_sets.items()},
    )


def read_mesh(path, convention="3mf"):
    """'(shape, section)' of the mesh file at 'path' (3MF, STL), with each object in the colour it states.

    One object - every STL, and most 3MF files - is the shape it always was. A
    3MF holds an object per colour where OpenSCAD wrote it (see
    'part_factory_scad'), and then the part is all of them, each in the colour
    its base material displays, stated under 'convention' for the core to
    convert. An object whose triangles are in base materials of their own - as
    PartCAD's 3MF exporter writes a part of several colours (see 'cmf_3mf') - is
    read a face per triangle, each face in its triangle's. What this process
    noted before is not this file's, and is forgotten first.
    """
    import os

    import build123d as b3d

    import ocp_serialize

    is_3mf = str(path).lower().endswith(".3mf")
    copy = None
    try:
        try:
            meshed = b3d.Mesher().read(path)
        except Exception:
            # A 3MF lib3mf refuses as another tool wrote it - a colour group of
            # the materials extension as an object's colour, most often - can be
            # one it reads once that is said the way the core specification says
            # it, and the copy is then what is read, colours and all.
            import cmf_3mf

            copy = cmf_3mf.readable_copy(path) if is_3mf else None
            if copy is None:
                raise
            meshed = b3d.Mesher().read(copy)
        if len(meshed) == 1:
            shape = meshed[0].wrapped
        else:
            shape = ocp_serialize.compound_of([mesh.wrapped for mesh in meshed])
        reset()
        origin = "raw:" + convention
        per_triangle = None
        if is_3mf:
            import cmf_3mf

            per_triangle = cmf_3mf.read(copy or path)
            if per_triangle is not None and len(per_triangle) != len(meshed):
                per_triangle = None
    finally:
        if copy is not None:
            os.remove(copy)
    for index, mesh in enumerate(meshed):
        bases = per_triangle[index][2] if per_triangle is not None else []
        if len(set(bases)) > 1:
            _note_triangles(mesh.wrapped, per_triangle[index], origin)
        else:
            note_build123d(mesh, origin=origin)
    return shape, section_for(shape)


def _float32(value) -> float:
    import struct

    return struct.unpack("<f", struct.pack("<f", value))[0]


def _corners(points):
    """What a triangle is known by, wherever it is: its three corners, rounded past what a 3MF's float holds."""
    return tuple(sorted(tuple(round(_float32(coordinate), 4) for coordinate in point) for point in points))


def _note_triangles(shape, read, origin):
    """Note each face of 'shape' - a mesh read a face per triangle - in the base material its triangle is in.

    'read' is what 'cmf_3mf.read' says of the object: its vertices, its
    triangles and the base each is in. A face is found by its corners, since
    the reader's sewing keeps the triangles but not their order; one whose
    triangle is in no base, or that is not found, is left unnoted.
    """
    import cmf_section
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_FACE, TopAbs_VERTEX
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    vertices, triangles, bases = read
    by_corners = {}
    for triangle, base in zip(triangles, bases):
        try:
            by_corners[_corners([vertices[i] for i in triangle])] = base
        except IndexError:
            continue
    faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, faces)
    for index in range(1, faces.Extent() + 1):
        face = faces.FindKey(index)
        corners = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(face, TopAbs_VERTEX, corners)
        points = []
        for corner in range(1, corners.Extent() + 1):
            point = BRep_Tool.Pnt_s(TopoDS.Vertex_s(corners.FindKey(corner)))
            points.append((point.X(), point.Y(), point.Z()))
        base = by_corners.get(_corners(points)) if len(points) == 3 else None
        if base is None:
            continue
        _name, rgba = base
        _note(face, cmf_section.CmfSet(color="#%02X%02X%02X" % rgba[:3], rgba=rgba, origin=origin), 1)
