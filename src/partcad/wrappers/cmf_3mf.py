#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A 3MF file's colours: base materials with display colours, per object and per triangle.

The 3MF core specification (chapter 5, "Material Resources") gives a mesh object
its appearance through a '<basematerials>' group: each '<base>' has a 'name', "to
convey design intent", and a 'displaycolor', sRGB with alpha, "for rendering
purposes only". An object names its default base with 'pid' and 'pindex', and a
triangle that is in another names it with its own 'pid' and 'p1'. That is how a
part of several colours is written here, and read back by 'cmf_capture.read_mesh'
(docs/design/cmf.md, section 9):

- 'triangle_sets' says which CMF set each triangle of the exported shape is in,
  counting triangles the way the exporter's mesher writes them;
- 'finish' adds the base materials to the 3MF the exporter wrote, one per set
  ('cmf_export.display_name' and its display colour), and points every object and
  triangle at its own - and makes the package one lib3mf reads, which CadQuery's
  writer's is not;
- 'read' gives each triangle of each mesh object of a 3MF the base it is in.

A part some of whose faces nobody coloured still has to give those triangles a
property, once its object has a default one; they are given the display default,
under 'cmf_export.UNSPECIFIED', which 'read' answers as nothing. A file with no
colour in it keeps the model the exporter wrote.

Plain Python and the standard library's XML, but for 'triangle_sets', which counts
a shape's triangles with OCP.
"""

import io
import os
import zipfile
import xml.etree.ElementTree as ElementTree

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
# The 3MF Materials and Properties Extension, whose colour groups 'readable_copy'
# rewrites as base materials.
MATERIAL = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
MODEL = "3D/3dmodel.model"


def _tag(name):
    return "{%s}%s" % (CORE, name)


def triangle_sets(whole, tree, warnings=None):
    """The CMF set of every triangle of 'whole', in the order a mesher writing it face by face writes them, or None.

    'whole' is 'wrapped' as an implementation is handed it, already meshed;
    'tree' the 'shape_tree' it was decoded from. The order is that of
    CadQuery's 'Shape.tessellate()', which the 3MF exporter writes through: the
    faces of 'whole' in 'TopExp::MapShapes' order, each one's triangles in the
    order its triangulation holds them, and a face with no triangulation
    skipped. None when no triangle is in a set that says anything - nothing to
    paint - or when the tree is not what 'whole' was decoded from.
    """
    import cmf_export
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    if tree is None or not cmf_export.carries_cmf(tree):
        return None
    pairs = cmf_export.paired(tree, whole, warnings)
    if not pairs:
        return None
    faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(whole, TopAbs_FACE, faces)
    sets = [None] * faces.Extent()
    memo = {}
    for leaf, shape in pairs:
        of_leaf = cmf_export.face_sets(leaf, memo, shape)
        under = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_FACE, under)
        for index in range(1, under.Extent() + 1):
            found = faces.FindIndex(under.FindKey(index))
            if found > 0 and index - 1 < len(of_leaf):
                sets[found - 1] = of_leaf[index - 1]
    if all(cmf_export.is_plain(cmf_set) for cmf_set in sets):
        return None
    result = []
    for index in range(1, faces.Extent() + 1):
        triangulation = BRep_Tool.Triangulation_s(TopoDS.Face_s(faces.FindKey(index)), TopLoc_Location())
        if triangulation is None:
            continue
        result.extend([sets[index - 1]] * triangulation.NbTriangles())
    return result


def _bases(per_triangle):
    """'(bases, index per triangle)': a base per set a triangle is in, and the display default where one is needed."""
    import appearance
    import cmf_export

    bases, keys, indices = [], {}, []
    for cmf_set in per_triangle:
        if cmf_export.is_plain(cmf_set) or cmf_set.rgba is None:
            key, name, rgba = None, cmf_export.UNSPECIFIED, appearance.parse(appearance.DEFAULT_COLOR)
            if cmf_set is not None and not cmf_export.is_plain(cmf_set):
                # Named, and drawn in nothing: named, in the display default.
                key, name = cmf_export.appearance_key(cmf_set), cmf_export.display_name(cmf_set)
        else:
            key, name, rgba = cmf_export.appearance_key(cmf_set), cmf_export.display_name(cmf_set), cmf_set.rgba
        if key not in keys:
            keys[key] = len(bases)
            bases.append((name, cmf_export.hex_rgba(rgba)))
        indices.append(keys[key])
    return bases, indices


CONTENT_TYPES = "[Content_Types].xml"
_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
# The content type of every part extension a 3MF package holds, as a 'Default'
# rather than an 'Override' of one part's name: lib3mf - which build123d's
# reader is, and so PartCAD's - refuses a package whose relationships are
# typed only by an 'Override', which is how CadQuery's writer types them.
_DEFAULTS = {
    "rels": "application/vnd.openxmlformats-package.relationships+xml",
    "model": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
}


def _content_types(data):
    """'[Content_Types].xml' with a 'Default' for every extension in _DEFAULTS it does not type by one."""
    ElementTree.register_namespace("", _TYPES)
    root = ElementTree.fromstring(data)
    typed = {element.get("Extension", "").lower() for element in root.findall("{%s}Default" % _TYPES)}
    missing = [extension for extension in _DEFAULTS if extension not in typed]
    if not missing:
        return data
    for position, extension in enumerate(missing):
        element = ElementTree.Element(
            "{%s}Default" % _TYPES, {"Extension": extension, "ContentType": _DEFAULTS[extension]}
        )
        # Defaults first, as the Open Packaging Conventions list them.
        root.insert(position, element)
    return ElementTree.tostring(root, xml_declaration=True, encoding="utf-8")


def finish(path, per_triangle=None) -> bool:
    """Make the 3MF at 'path' readable by lib3mf, and paint it with 'per_triangle' if given.

    'per_triangle' is what 'triangle_sets' answers, for the mesh objects of the
    file in document order: each set becomes a base material, and every object
    and triangle names its own. Answers whether the file was painted: one whose
    triangles are not as many as 'per_triangle' says - written by a mesher that
    counts them otherwise - is left unpainted, and the caller says so; one that
    is not a package at all is left as it is.
    """
    try:
        with zipfile.ZipFile(path) as source:
            members = [(info, source.read(info.filename)) for info in source.infolist()]
    except (zipfile.BadZipFile, OSError):
        # Not a package this can open: left as the writer wrote it.
        return False
    replaced = {}
    for info, data in members:
        if info.filename == CONTENT_TYPES:
            replaced[CONTENT_TYPES] = _content_types(data)
    painted = False
    model = next((data for info, data in members if info.filename == MODEL), None)
    if model is not None:
        ElementTree.register_namespace("", CORE)
        root = ElementTree.fromstring(model)
        changed = _renumbered(root)
        if per_triangle is not None and _painted(root, per_triangle):
            changed = painted = True
        if changed:
            replaced[MODEL] = ElementTree.tostring(root, xml_declaration=True, encoding="utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        for info, data in members:
            out.writestr(info, replaced.get(info.filename, data))
    with open(path, "wb") as f:
        f.write(buffer.getvalue())
    return painted


def _renumbered(root) -> bool:
    """Whether 'root' (a model part) had a resource numbered 0, which it now has not.

    A resource's id is a positive integer (the core specification's
    'ST_ResourceID'), and CadQuery's writer numbers its first object 0, which
    lib3mf refuses. Every id, and everything naming one - a component, a build
    item, a property group - moves up by one.
    """
    resources = root.find(_tag("resources"))
    if resources is None or not any(element.get("id") == "0" for element in resources):
        return False

    def moved(element, key):
        value = element.get(key)
        if value is not None and value.isdigit():
            element.set(key, str(int(value) + 1))

    for element in root.iter():
        if element in resources:
            moved(element, "id")
        moved(element, "objectid")
        moved(element, "pid")
    return True


def _colour_groups_as_bases(root) -> bool:
    """Whether 'root' (a model part) had a colour group of the materials extension, which is now a base material group.

    The 3MF Materials and Properties Extension lets an object or a triangle take
    its colour from an '<m:colorgroup>', which is how a good many slicers and CAD
    tools write a coloured mesh - and lib3mf, which build123d's reader is, refuses
    an object whose default property is one ('Lib3MFException 5: unknown error').
    A colour group and a base material group are both property groups, indexed
    alike by an object's 'pindex' and a triangle's 'p1', so each colour group
    becomes a '<basematerials>' of the same id in the same place, with a '<base>'
    displaying each of its colours, and whatever named the one names the other.
    """
    resources = root.find(_tag("resources"))
    if resources is None:
        return False
    changed = False
    for position, group in enumerate(list(resources)):
        if group.tag != "{%s}colorgroup" % MATERIAL:
            continue
        bases = ElementTree.Element(_tag("basematerials"), {"id": group.get("id", "")})
        for index, colour in enumerate(group.findall("{%s}color" % MATERIAL)):
            ElementTree.SubElement(
                bases,
                _tag("base"),
                {"name": "colour %d" % (index + 1), "displaycolor": colour.get("color") or "#FFFFFFFF"},
            )
        resources[position] = bases
        changed = True
    return changed


def readable_copy(path):
    """A copy of the 3MF at 'path' that lib3mf has a better chance of reading, or None when nothing in it would change.

    What it changes is what lib3mf is known to refuse in a file another tool
    wrote: its colour groups (see '_colour_groups_as_bases'), a resource
    numbered 0 (see '_renumbered') and relationships typed only by an
    'Override' (see '_content_types'). The copy is a temporary file, the
    caller's to delete; the file at 'path' is left as it is.
    """
    import tempfile

    try:
        with zipfile.ZipFile(path) as source:
            members = [(info, source.read(info.filename)) for info in source.infolist()]
    except (zipfile.BadZipFile, OSError):
        return None
    replaced = {}
    for info, data in members:
        try:
            if info.filename == CONTENT_TYPES:
                fixed = _content_types(data)
                if fixed != data:
                    replaced[info.filename] = fixed
            elif info.filename.endswith(".model"):
                ElementTree.register_namespace("", CORE)
                ElementTree.register_namespace("m", MATERIAL)
                root = ElementTree.fromstring(data)
                if _colour_groups_as_bases(root) | _renumbered(root):
                    replaced[info.filename] = ElementTree.tostring(root, xml_declaration=True, encoding="utf-8")
        except ElementTree.ParseError:
            return None
    if not replaced:
        return None
    handle, copy = tempfile.mkstemp(suffix=".3mf")
    with os.fdopen(handle, "wb") as f, zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as out:
        for info, data in members:
            out.writestr(info, replaced.get(info.filename, data))
    return copy


def _painted(root, per_triangle) -> bool:
    """Whether 'root' (a model part) is given a base material per set of 'per_triangle': not if its triangles are not those."""
    resources = root.find(_tag("resources"))
    if resources is None:
        return False
    objects = []
    for element in resources.findall(_tag("object")):
        triangles = element.find("%s/%s" % (_tag("mesh"), _tag("triangles")))
        if triangles is not None:
            objects.append((element, triangles.findall(_tag("triangle"))))
    if sum(len(triangles) for _element, triangles in objects) != len(per_triangle):
        return False

    bases, indices = _bases(per_triangle)
    ids = [int(value) for value in (element.get("id") for element in resources) if value and value.isdigit()]
    group_id = str(max(ids, default=0) + 1)
    group = ElementTree.Element(_tag("basematerials"), {"id": group_id})
    for name, color in bases:
        ElementTree.SubElement(group, _tag("base"), {"name": name, "displaycolor": color})
    # Before everything that names it: a resource is defined before it is used.
    resources.insert(0, group)

    offset = 0
    for element, triangles in objects:
        mine = indices[offset : offset + len(triangles)]
        offset += len(triangles)
        if not mine:
            continue
        default = max(sorted(set(mine)), key=mine.count)
        element.set("pid", group_id)
        element.set("pindex", str(default))
        for triangle, index in zip(triangles, mine):
            if index != default:
                triangle.set("pid", group_id)
                triangle.set("p1", str(index))
    return True


def read(path):
    """'[(vertices, triangles, bases), ...]' for every mesh object of the 3MF at 'path', in document order.

    'vertices' are '(x, y, z)' as the file states them, 'triangles' the vertex
    indices of each, and 'bases' the '(name, rgba)' each triangle is in - its
    own property, else its object's - or None where it is in none, or in
    UNSPECIFIED. None for a file that is not a 3MF this can read.
    """
    import appearance
    import cmf_export

    try:
        with zipfile.ZipFile(path) as source:
            names = [name for name in source.namelist() if name.endswith(".model")]
            if MODEL in names:
                names = [MODEL]
            root = ElementTree.fromstring(source.read(names[0])) if names else None
    except (zipfile.BadZipFile, ElementTree.ParseError, OSError, KeyError):
        return None
    if root is None:
        return None
    resources = root.find(_tag("resources"))
    if resources is None:
        return None
    groups = {}
    for group in resources.findall(_tag("basematerials")):
        entries = []
        for base in group.findall(_tag("base")):
            name = base.get("name") or ""
            rgba = appearance.parse(base.get("displaycolor") or "")
            entries.append(None if name == cmf_export.UNSPECIFIED or rgba is None else (name, rgba))
        groups[group.get("id")] = entries

    def base(pid, index):
        entries = groups.get(pid)
        try:
            return entries[int(index)] if entries is not None and index is not None else None
        except (ValueError, IndexError):
            return None

    found = []
    for element in resources.findall(_tag("object")):
        mesh = element.find(_tag("mesh"))
        if mesh is None:
            continue
        vertices = [
            (float(vertex.get("x", 0)), float(vertex.get("y", 0)), float(vertex.get("z", 0)))
            for vertex in mesh.iterfind("%s/%s" % (_tag("vertices"), _tag("vertex")))
        ]
        default = base(element.get("pid"), element.get("pindex"))
        triangles, bases = [], []
        for triangle in mesh.iterfind("%s/%s" % (_tag("triangles"), _tag("triangle"))):
            triangles.append(tuple(int(triangle.get(key, 0)) for key in ("v1", "v2", "v3")))
            pid = triangle.get("pid") or element.get("pid")
            bases.append(base(pid, triangle.get("p1")) if triangle.get("p1") is not None else default)
        found.append((vertices, triangles, bases))
    return found
