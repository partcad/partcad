#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A STEP file's geometry, with the colours and materials it states (docs/design/cmf.md, section 7).

Read through OCCT's XCAF reader, 'STEPCAFControl_Reader', which keeps what the
plain 'STEPControl_Reader' discards: the styles on faces, solids and products
(CAx-IF *Model Styling and Organization*), and the materials on products. The
geometry is the reader's own - the very shapes the plain reader transfers, in
the same order, byte for byte the BREP it wrote before (which a test holds it
to) - so a STEP part is the same part it was, now with CMF.

What the file states is written into the section as it stated it, in sets of
origin 'raw:step' (see 'partcad.cmf_conventions'), for the core to convert: a
colour as '#RRGGBB' of its value, a material by its name. A STEP colour's
numbers are sRGB, which is how every CAD tool that writes them means them and
how OCCT treats them: its reader turns a 'COLOUR_RGB' into the linear values a
'Quantity_Color' holds, and its writer turns them back. So a colour is read
here as 'Values(Quantity_TOC_sRGB)' and written from 'Quantity_TOC_sRGB' - the
numbers in the file - and never as 'Red()', which is the linear value and
reads a file's #C91A09 as #950301.

Inner wins, as in STEP itself: a face's own style over its shell's or its
solid's, a solid's over its compound's.

A file PartCAD wrote says more (see 'Writer'): the product structure and names
of what it exported, and on every part's product a user-defined attribute
(the CAx-IF practice's 'GENERAL_PROPERTY' form, which OCCT's reader reads into a
'TDataStd_NamedData' on the product's label) holding PartCAD's own references
for every face and solid of it: PARTCAD_ATTRIBUTE. A product whose attribute
still describes it - as many faces as it says, each in the colour the file
draws it in - is read in PartCAD's own terms, in sets of origin 'raw:partcad',
which the core takes as references whatever 'cmfConvention' says, as it takes
what 'set_cmf' says ('partcad.cmf_conventions.convert'). One that no longer
does - another tool has edited the file and kept the attribute - is read by
value like any other, and says so.
"""

import json
import os
import sys
import urllib.parse

import cmf_capture
import ocp_serialize

ORIGIN = "raw:step"

# The origin of what a file PartCAD wrote states in PartCAD's own terms (see
# the module docstring): the one 'set_cmf' states in.
PARTCAD = cmf_capture.PARTCAD

# The user-defined attribute PartCAD writes on a part's product (see
# '_add_attribute'): the name of its 'PROPERTY_DEFINITION', which is the key
# OCCT's reader files it under on the product's label, and of the
# 'DESCRIPTIVE_REPRESENTATION_ITEM' whose description holds it.
PARTCAD_ATTRIBUTE = "partcad.cmf"
USER_DEFINED_ATTRIBUTES = "user defined attributes"

# The version of what PARTCAD_ATTRIBUTE holds, under "partcad": a reader that
# finds another one reads the file by value.
ATTRIBUTE_VERSION = 1

# What may be written as it is into the attribute's text. Everything else -
# every non-ASCII character, and the quote and the backslash a STEP string
# escapes - is percent-encoded: the text stays seven-bit and needs no escaping,
# whichever way the writer and the reader of a STEP string treat either.
_SAFE = ' !"#$&()*+,-./:;<=>?@[]^_`{|}~'

# Outermost first, so that what is said of a part of it later wins.
_ORDER = ("TopAbs_COMPOUND", "TopAbs_COMPSOLID", "TopAbs_SOLID", "TopAbs_SHELL", "TopAbs_FACE")


def _byte(value) -> int:
    return max(0, min(255, int(round(float(value) * 255))))


def _color(style):
    """'(designation, rgba)' of a style's surface colour, or None."""
    if not style.IsSetColorSurf():
        return None
    return _designated(style.GetColorSurfRGBA())


def _designated(rgba):
    """'(designation, rgba)' of a 'Quantity_ColorRGBA': the sRGB numbers a file states, as '#RRGGBB' and bytes."""
    from OCP.Quantity import Quantity_TOC_sRGB

    red, green, blue = (_byte(value) for value in rgba.GetRGB().Values(Quantity_TOC_sRGB))
    return "#%02X%02X%02X" % (red, green, blue), (red, green, blue, float(rgba.Alpha()))


def _quantity(rgba):
    """A 'Quantity_ColorRGBA' of an sRGB '(red, green, blue, alpha)', the bytes a section holds."""
    from OCP.Quantity import Quantity_Color, Quantity_ColorRGBA, Quantity_TOC_sRGB

    color = Quantity_Color(rgba[0] / 255.0, rgba[1] / 255.0, rgba[2] / 255.0, Quantity_TOC_sRGB)
    return Quantity_ColorRGBA(color, float(rgba[3]))


def _labels(shape_tool, root):
    """Every shape label under 'root', the shapes its components refer to included, each once."""
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_ShapeTool

    seen = set()
    pending = [root]
    while pending:
        label = pending.pop()
        if XCAFDoc_ShapeTool.IsReference_s(label):
            referred = TDF_Label()
            if XCAFDoc_ShapeTool.GetReferredShape_s(label, referred):
                label = referred
        entry = label.EntryDumpToString() if hasattr(label, "EntryDumpToString") else str(label.Tag())
        if entry in seen:
            continue
        seen.add(entry)
        yield label
        children = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetComponents_s(label, children, False)
        for index in range(1, children.Length() + 1):
            pending.append(children.Value(index))


def open_document(path):
    """'(document, reader)': the STEP file at 'path' read into an XCAF document. Raises what reading raises."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application

    document = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    XCAFApp_Application.GetApplication_s().NewDocument(TCollection_ExtendedString("MDTV-XCAF"), document)
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetNameMode(True)
    reader.SetMatMode(True)
    reader.SetLayerMode(True)
    # User-defined attributes, into a 'TDataStd_NamedData' on each product's
    # label: what PartCAD's own references are carried in (PARTCAD_ATTRIBUTE).
    reader.SetMetaMode(True)
    if reader.ReadFile(path) != IFSelect_RetDone:
        raise Exception("STEP File could not be loaded")
    if not reader.Transfer(document):
        raise Exception("STEP File could not be transferred")
    return document, reader


class Facts:
    """What a document states: the colour of each styled shape, and the material of each product's shapes."""

    def __init__(self, document):
        from OCP.TDF import TDF_LabelSequence
        from OCP.TopLoc import TopLoc_Location
        from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
        from OCP.XCAFPrs import XCAFPrs, XCAFPrs_IndexedDataMapOfShapeStyle

        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
        roots = TDF_LabelSequence()
        shape_tool.GetFreeShapes(roots)
        styles = XCAFPrs_IndexedDataMapOfShapeStyle()
        for index in range(1, roots.Length() + 1):
            XCAFPrs.CollectStyleSettings_s(roots.Value(index), TopLoc_Location(), styles)
        # '(shape, (designation, rgba))', outermost first (see _ORDER).
        self.colors = []
        for index in range(1, styles.Extent() + 1):
            color = _color(styles.FindFromIndex(index))
            if color is not None:
                self.colors.append((styles.FindKey(index), color))
        self.colors.sort(key=lambda pair: _rank(pair[0]))
        # The same of every definition on its own, unplaced: what a part taken
        # out of the assembly is, whatever an instance of it overrides.
        self.definition_colors = []
        # '(shape, name)' for every product made of a material - and every
        # sub-shape: OCCT's reader files the material of a product of several
        # solids under the first of them rather than under the product.
        self.materials = []
        # '(definition, Table)' for every product whose PartCAD attribute
        # still describes it (see '_table').
        self.tables = []
        for r in range(1, roots.Length() + 1):
            for label in _labels(shape_tool, roots.Value(r)):
                material = _material_of(label)
                if material:
                    self.materials.append((XCAFDoc_ShapeTool.GetShape_s(label), material))
                if XCAFDoc_ShapeTool.IsAssembly_s(label):
                    continue
                subs = TDF_LabelSequence()
                XCAFDoc_ShapeTool.GetSubShapes_s(label, subs)
                for index in range(1, subs.Length() + 1):
                    material = _material_of(subs.Value(index))
                    if material:
                        self.materials.append((XCAFDoc_ShapeTool.GetShape_s(subs.Value(index)), material))
                own = XCAFPrs_IndexedDataMapOfShapeStyle()
                XCAFPrs.CollectStyleSettings_s(label, TopLoc_Location(), own)
                stated = []
                for index in range(1, own.Extent() + 1):
                    color = _color(own.FindFromIndex(index))
                    if color is not None:
                        stated.append((own.FindKey(index), color))
                        self.definition_colors.append((own.FindKey(index), color))
                table = _table(label, XCAFDoc_ShapeTool.GetShape_s(label), stated)
                if table is not None:
                    self.tables.append((table.definition, table))
        self.definition_colors.sort(key=lambda pair: _rank(pair[0]))

    def __bool__(self):
        return bool(self.colors or self.definition_colors or self.materials or self.tables)


def _rank(shape) -> int:
    name = shape.ShapeType().name
    return _ORDER.index(name) if name in _ORDER else 0


def section_of(shape, facts, by_partner=False):
    """The CMF section of 'shape' from 'facts', or None if they say nothing of it.

    'by_partner' matches a styled shape by what it is rather than where it is,
    with what its definition states: for a part taken out of an assembly, whose
    solids are its definition's and sit where the assembly does not put them,
    and which is its definition whatever an instance of it overrides. The whole
    file's geometry, read as it is placed, is matched exactly (each instance by
    its own placement, overrides and all).
    """
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    import cmf_section

    if not facts:
        return None

    def mapped(of, kind):
        found = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(of, kind, found)
        return found

    faces = mapped(shape, TopAbs_FACE)
    solids = mapped(shape, TopAbs_SOLID)
    face_index = _Index(faces, by_partner)
    # A colour is matched the way the faces are: by placement for the whole
    # file, where a style collected for one instance is that instance's alone.
    solid_index = _Index(solids, by_partner)
    # A product's material is every instance of it, wherever each is placed.
    material_index = solid_index if by_partner else _Index(solids, True)

    face_colors, solid_colors = {}, {}
    for key, color in facts.definition_colors if by_partner else facts.colors:
        under = mapped(key, TopAbs_FACE)
        if key.ShapeType().name == "TopAbs_SOLID":
            matched = solid_index.of(key)
            for index in matched:
                solid_colors[index] = color
            if matched:
                # More specific than the compound around it, whose style was
                # written onto these faces before it: the solid's own wins, and
                # a face's own - later in the order - still wins over that.
                for i in range(1, under.Extent() + 1):
                    for index in face_index.of(under.FindKey(i)):
                        face_colors.pop(index, None)
                continue
        for i in range(1, under.Extent() + 1):
            for index in face_index.of(under.FindKey(i)):
                face_colors[index] = color

    solid_materials = {}
    for definition, material in facts.materials:
        under = mapped(definition, TopAbs_SOLID)
        for i in range(1, under.Extent() + 1):
            for index in material_index.of(under.FindKey(i)):
                solid_materials.setdefault(index, material)

    # What PartCAD's own attribute says of the products it still describes
    # (see '_table'): a fact of the definition, so matched by partner like a
    # material, and in place of what the file states by value.
    table_faces, table_solids = {}, {}
    if facts.tables:
        partners = _Index(faces, True)
        for definition, table in facts.tables:
            for kind, entries, index, into in (
                (TopAbs_FACE, table.faces, partners, table_faces),
                (TopAbs_SOLID, table.solids, material_index, table_solids),
            ):
                under = mapped(definition, kind)
                for i in range(1, under.Extent() + 1):
                    if entries[i - 1] is None:
                        continue
                    for found in index.of(under.FindKey(i)):
                        into[found] = entries[i - 1]

    if not face_colors and not solid_colors and not solid_materials and not table_faces and not table_solids:
        return None
    palette = {}

    def set_of(color=None, material=None):
        key = (color, material)
        if key not in palette:
            palette[key] = cmf_section.CmfSet(
                color=color[0] if color else None,
                rgba=color[1] if color else None,
                material=material,
                origin=ORIGIN,
            )
        return palette[key]

    solid_sets = {}
    for index in set(solid_colors) | set(solid_materials):
        solid_sets[solids.FindKey(index)] = set_of(solid_colors.get(index), solid_materials.get(index))
    face_sets = {faces.FindKey(index): set_of(color) for index, color in face_colors.items()}
    for index, cmf_set in table_faces.items():
        face_sets[faces.FindKey(index)] = cmf_set
    for index, cmf_set in table_solids.items():
        solid_sets[solids.FindKey(index)] = cmf_set
    return ocp_serialize.cmf_section_for(shape, faces=face_sets, solids=solid_sets)


class _Index:
    """Where a shape is among 'found' (an indexed map of sub-shapes): exactly, or by partner."""

    def __init__(self, found, by_partner):
        from OCP.TopTools import TopTools_IndexedMapOfShape

        self.found = found
        self.by_partner = by_partner
        if by_partner:
            self.definitions = TopTools_IndexedMapOfShape()
            self.places = []
            for index in range(1, found.Extent() + 1):
                definition = _unlocated_key(found.FindKey(index))
                if not self.definitions.Contains(definition):
                    self.definitions.Add(definition)
                    self.places.append([])
                self.places[self.definitions.FindIndex(definition) - 1].append(index)

    def of(self, shape) -> list:
        if not self.by_partner:
            return [self.found.FindIndex(shape)] if self.found.Contains(shape) else []
        definition = _unlocated_key(shape)
        if not self.definitions.Contains(definition):
            return []
        return list(self.places[self.definitions.FindIndex(definition) - 1])


def read(path):
    """'(shape, section)' of the STEP file at 'path'; the section is None when the file states no CMF.

    Raises what the reader raises; the caller falls back to the plain reader,
    which reads what OCCT can read at all.
    """
    document, reader = open_document(path)
    inner = reader.ChangeReader()
    shape = ocp_serialize.compound_of([inner.Shape(index + 1) for index in range(inner.NbShapes())])
    return shape, section_of(shape, Facts(document))


def instance_color(label):
    """'(designation, rgba)' of the colour an assembly's instance ('label', a component) sets itself, or None.

    What STEP calls an overriding style on an occurrence: the instance is drawn
    in it whatever its definition says, which is how PartCAD reads it too.
    """
    from OCP.Quantity import Quantity_ColorRGBA
    from OCP.XCAFDoc import XCAFDoc_ColorGen, XCAFDoc_ColorSurf, XCAFDoc_ColorTool, XCAFDoc_ShapeTool

    if not XCAFDoc_ShapeTool.IsReference_s(label):
        return None
    for kind in (XCAFDoc_ColorSurf, XCAFDoc_ColorGen):
        rgba = Quantity_ColorRGBA()
        if XCAFDoc_ColorTool.GetColor_s(label, kind, rgba):
            return _designated(rgba)
    return None


def _is_reference(cmf_set) -> bool:
    """Whether a set names anything in PartCAD's own terms: a set of the core's, or one 'set_cmf' states.

    A set still in another tool's terms ('raw:step', from a file being
    imported) names nothing PartCAD declared, and is written by value alone.
    """
    if cmf_set is None or (cmf_set.color is None and cmf_set.material is None and cmf_set.finish is None):
        return False
    origin = cmf_set.origin or ""
    return not origin.startswith("raw:") or origin == PARTCAD


def _runs(indices) -> list:
    runs = []
    for index in indices:
        if runs and runs[-1][1] == index:
            runs[-1][0] += 1
        else:
            runs.append([1, index])
    return runs


def _expanded(runs, limit) -> list:
    """The indices 'runs' ('[length, value]' pairs) stand for; ValueError if they stand for more than 'limit'.

    Counted before anything is expanded: the runs are the file's to say, and a
    length of 10**12 is not a list to build only to find it is the wrong one.
    """
    pairs = [(int(length), int(value)) for length, value in runs]
    total = sum(length for length, _value in pairs)
    if total > limit or any(length < 0 for length, _value in pairs):
        raise ValueError("its runs come to %d, and the product has %d" % (total, limit))
    indices = []
    for length, value in pairs:
        indices.extend([value] * length)
    return indices


def encode_table(face_sets, solid_sets):
    """The text of PARTCAD_ATTRIBUTE for a product of these faces and solids, or None if it names nothing.

    'face_sets' and 'solid_sets' are a 'cmf_section.CmfSet' per face and per
    solid of the product, in 'TopExp::MapShapes' order. What is written is
    every set that names something - its references, and the display it is
    drawn in - and which of them each face and each solid is in, as runs, the
    way the CMF section addresses them. A face or a solid in nothing is -1. A
    solid's set is what it is made of, and the colour and finish its faces
    take where they state none, as a section holds it.
    """
    import cmf_export

    if not any(_is_reference(cmf_set) for cmf_set in list(face_sets) + list(solid_sets)):
        return None
    sets, index = [], {}

    def of(cmf_set):
        if cmf_set is None:
            return -1
        entry = {}
        if _is_reference(cmf_set):
            entry = {key: getattr(cmf_set, key) for key in ("color", "material", "finish") if getattr(cmf_set, key)}
        if cmf_set.rgba is not None:
            entry["display"] = cmf_export.hex_rgba(cmf_set.rgba)
        if not entry:
            return -1
        key = tuple(sorted(entry.items()))
        if key not in index:
            index[key] = len(sets)
            sets.append(entry)
        return index[key]

    faces = [of(cmf_set) for cmf_set in face_sets]
    solids = [of(cmf_set) for cmf_set in solid_sets]
    text = json.dumps(
        {"partcad": ATTRIBUTE_VERSION, "sets": sets, "faces": _runs(faces), "solids": _runs(solids)},
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    )
    return urllib.parse.quote(text, safe=_SAFE)


class Table:
    """What PARTCAD_ATTRIBUTE says of one product: a set (or None) per face and per solid of 'definition'."""

    def __init__(self, definition, faces, solids) -> None:
        self.definition = definition
        self.faces = faces
        self.solids = solids


def _close(one, other) -> bool:
    """Whether two '(red, green, blue, alpha)' are one colour, give or take what a STEP real rounds off."""
    if one is None or other is None:
        return one is None and other is None
    return all(abs(a - b) <= 1 for a, b in zip(one[:3], other[:3])) and abs(one[3] - other[3]) <= 1.5 / 255


def decode_table(text, definition, drawn):
    """The 'Table' 'text' (PARTCAD_ATTRIBUTE's) is of 'definition', or None with the reason why not.

    'drawn' is the colour the file draws each face of 'definition' in, or None,
    in 'TopExp::MapShapes' order. The attribute is taken only where it still
    describes the product: as many faces and solids as it says, each face in
    the colour it says - so that a file another tool has edited, keeping the
    attribute, is read for what it now says rather than for what it once did.
    """
    import appearance
    import cmf_section
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    solid_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(definition, TopAbs_SOLID, solid_map)
    try:
        data = json.loads(urllib.parse.unquote(text))
        version = data.get("partcad")
        if version != ATTRIBUTE_VERSION:
            return None, "it is of version %r, and this PartCAD reads %d" % (version, ATTRIBUTE_VERSION)
        sets = [entry if isinstance(entry, dict) else {} for entry in data.get("sets") or []]
        faces = _expanded(data.get("faces") or [], len(drawn))
        solids = _expanded(data.get("solids") or [], solid_map.Extent())
    except (ValueError, TypeError, AttributeError) as e:
        return None, "it cannot be read (%s)" % e
    if len(faces) != len(drawn) or len(solids) != solid_map.Extent():
        return None, "it describes %d faces and %d solids, and the product has %d and %d" % (
            len(faces),
            len(solids),
            len(drawn),
            solid_map.Extent(),
        )

    def entry(i):
        return sets[i] if 0 <= i < len(sets) else {}

    result_faces = []
    for i, (index, stated) in enumerate(zip(faces, drawn)):
        found = entry(index)
        display = found.get("display")
        wanted = appearance.parse(display) if display else None
        if not _close(wanted, stated):
            return None, "face %d is drawn in %s, and the attribute says %s" % (
                i + 1,
                _display_of(stated),
                display or "nothing",
            )
        if not any(found.get(key) for key in ("color", "material", "finish")):
            result_faces.append(None)
            continue
        result_faces.append(
            cmf_section.CmfSet(
                color=found.get("color"),
                material=found.get("material"),
                finish=found.get("finish"),
                origin=PARTCAD,
                rgba=stated if found.get("color") else None,
            )
        )
    result_solids = []
    for index in solids:
        found = entry(index)
        if not any(found.get(key) for key in ("color", "material", "finish")):
            result_solids.append(None)
            continue
        display = appearance.parse(found["display"]) if found.get("color") and found.get("display") else None
        result_solids.append(
            cmf_section.CmfSet(
                color=found.get("color"),
                material=found.get("material"),
                finish=found.get("finish"),
                origin=PARTCAD,
                rgba=display,
            )
        )
    return Table(definition, result_faces, result_solids), None


def _display_of(rgba) -> str:
    if rgba is None:
        return "nothing"
    import cmf_export

    return cmf_export.hex_of(rgba)


def _table(label, definition, stated):
    """The 'Table' a product's PARTCAD_ATTRIBUTE holds, or None: when it holds none, or no longer describes it.

    'stated' is '[(shape, (designation, rgba)), ...]': the styles of the
    product's definition, unplaced, as 'XCAFPrs.CollectStyleSettings' finds them.
    """
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_NamedData
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    attribute = _attribute(label, TDataStd_NamedData.GetID_s())
    if attribute is None or not hasattr(attribute, "HasString"):
        return None
    key = TCollection_ExtendedString(PARTCAD_ATTRIBUTE)
    if not attribute.HasString(key):
        return None
    text = attribute.GetString(key).ToExtString()

    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(definition, TopAbs_FACE, face_map)
    drawn = [None] * face_map.Extent()
    # Outermost first, so that a face's own style wins over its solid's.
    for shape, (_designation, rgba) in sorted(stated, key=lambda pair: _rank(pair[0])):
        under = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_FACE, under)
        for i in range(1, under.Extent() + 1):
            index = face_map.FindIndex(under.FindKey(i))
            if index > 0:
                drawn[index - 1] = rgba
    table, reason = decode_table(text, definition, drawn)
    if table is None:
        print(
            "PartCAD's CMF attribute on a product of this STEP file is not read, because %s; "
            "its colours and materials are read by value" % reason,
            file=sys.stderr,
        )
    return table


class Writer:
    """An XCAF document being filled with products, and written to a STEP file once it holds them all.

    What PartCAD says of a part goes on the part's product, in the forms every
    CAD tool reads, and once more in PartCAD's own (docs/design/cmf.md, section
    9, "Exports"):

    - each face's display colour, as sRGB: on the product where every face of
      it is in one colour, on a solid where every face of the solid is, and on
      the face otherwise - the CAx-IF practice's styles on a product, a solid
      and a face, with the more specific winning;
    - the material, where every solid of the product is made of the same one:
      STEP states a material per product, which is the one place OCCT writes it.
      Its name is the material's reference, which is what reading the file back
      with the 'partcad' convention takes it for, its description what the
      declaration says it is, and its density the declaration's, in the g/cm^3
      the CAx-IF practice writes (a declaration states kg/m^3);
    - PARTCAD_ATTRIBUTE, a user-defined attribute holding PartCAD's references
      for every face and solid of the product (see 'encode_table'): the colours
      by the declarations that claim them, the finishes, and a material per
      solid where the product has several. That is what makes the file read
      back as the part it was: colour by colour a STEP file states only values,
      and OCCT writes neither a colour's name nor a finish.

    Names are written after the transfer rather than handed to OCCT: its writer
    encodes a 'TDataStd_Name' that is not ASCII twice, and a product has to be
    found again in the model, to hang the attribute on, by something nothing
    else is called. So each product and each component is transferred under a
    token, and given its name, as UTF-8 as every reader takes it, once found.
    """

    def __init__(self, facts=None) -> None:
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.TDocStd import TDocStd_Document
        from OCP.XCAFApp import XCAFApp_Application
        from OCP.XCAFDoc import XCAFDoc_DocumentTool

        self.document = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
        XCAFApp_Application.GetApplication_s().NewDocument(TCollection_ExtendedString("MDTV-XCAF"), self.document)
        main = self.document.Main()
        self.shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(main)
        self.shape_tool.SetAutoNaming_s(False)
        self.color_tool = XCAFDoc_DocumentTool.ColorTool_s(main)
        self.material_tool = XCAFDoc_DocumentTool.MaterialTool_s(main)
        # What the core resolved of the declarations the shapes name: under
        # "materials", each reference's 'density' (kg/m^3) and 'description'.
        self.facts = facts if isinstance(facts, dict) else {}
        self._definitions = {}
        self._materials = {}
        # Token -> (name, PARTCAD_ATTRIBUTE text or None), for every label named.
        self._names = {}

    def _token(self, label, name, table=None) -> None:
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.TDataStd import TDataStd_Name

        token = "PARTCAD-%08d" % (len(self._names) + 1)
        self._names[token] = (str(name or ""), table)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(token))

    def part(self, shape, name, face_sets=None, solid_sets=None, key=None):
        """The product of 'shape', unplaced, in the colours, material and references given; added once per 'key'.

        'face_sets' and 'solid_sets' are a 'cmf_section.CmfSet' per face and
        per solid of 'shape', in 'TopExp::MapShapes' order, or None for none.
        'shape' is taken as it is placed in its own frame: a shape with a
        location of its own is a product placed by the caller.
        """
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
        from OCP.TDF import TDF_Label
        from OCP.TopLoc import TopLoc_Location

        if key is not None and key in self._definitions:
            return self._definitions[key]
        definition = shape.Located(TopLoc_Location())
        found = TDF_Label()
        if self.shape_tool.FindShape(definition, found, False):
            # The same geometry in other CMF - a part drawn in an assembly's
            # colour in one place and its own in another - is another product,
            # and XCAF keeps one label per shape: a copy has the same faces, in
            # the same order, under another.
            definition = BRepBuilderAPI_Copy(definition, True, False).Shape()
        label = self.shape_tool.AddShape(definition, False, False)
        face_sets = list(face_sets or [])
        solid_sets = list(solid_sets or [])
        self._token(label, name, encode_table(face_sets, solid_sets))
        self._color(label, definition, face_sets)
        self._material(label, solid_sets, face_sets)
        if key is not None:
            self._definitions[key] = label
        return label

    def assembly(self, name):
        """A new assembly product, named 'name', for 'place' to put components into."""
        label = self.shape_tool.NewShape()
        self._token(label, name)
        return label

    def place(self, parent, child, location=None, name=None):
        """'child' (a product) placed in 'parent' (an assembly) at 'location', a 'TopLoc_Location'."""
        from OCP.TopLoc import TopLoc_Location

        component = self.shape_tool.AddComponent(parent, child, location or TopLoc_Location())
        if name:
            self._token(component, name)
        return component

    def _color(self, label, definition, face_sets) -> None:
        from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
        from OCP.TopExp import TopExp
        from OCP.TopTools import TopTools_IndexedMapOfShape
        from OCP.XCAFDoc import XCAFDoc_ColorSurf

        faces = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(definition, TopAbs_FACE, faces)
        if faces.Extent() != len(face_sets) or not any(cmf_set.rgba is not None for cmf_set in face_sets):
            return
        colors = [cmf_set.rgba for cmf_set in face_sets]
        if all(rgba == colors[0] for rgba in colors):
            self.color_tool.SetColor(label, _quantity(colors[0]), XCAFDoc_ColorSurf)
            return
        done = set()
        solids = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(definition, TopAbs_SOLID, solids)
        for s in range(1, solids.Extent() + 1):
            under = TopTools_IndexedMapOfShape()
            TopExp.MapShapes_s(solids.FindKey(s), TopAbs_FACE, under)
            indices = [faces.FindIndex(under.FindKey(i)) - 1 for i in range(1, under.Extent() + 1)]
            indices = [index for index in indices if index >= 0]
            if indices and colors[indices[0]] is not None and all(colors[i] == colors[indices[0]] for i in indices):
                sub = self.shape_tool.AddSubShape(label, solids.FindKey(s))
                if not sub.IsNull():
                    self.color_tool.SetColor(sub, _quantity(colors[indices[0]]), XCAFDoc_ColorSurf)
                    done.update(indices)
        for index, rgba in enumerate(colors):
            if rgba is None or index in done:
                continue
            sub = self.shape_tool.AddSubShape(label, faces.FindKey(index + 1))
            if not sub.IsNull():
                self.color_tool.SetColor(sub, _quantity(rgba), XCAFDoc_ColorSurf)

    def _material(self, label, solid_sets, face_sets) -> None:
        from OCP.TCollection import TCollection_HAsciiString

        sets = solid_sets or face_sets[:1]
        materials = {getattr(cmf_set, "material", None) for cmf_set in sets}
        if len(materials) != 1 or None in materials:
            return
        name = materials.pop()
        if name not in self._materials:
            declared = (self.facts.get("materials") or {}).get(name) or {}
            density = declared.get("density")
            description = declared.get("description") or ""
            self._materials[name] = self.material_tool.AddMaterial(
                TCollection_HAsciiString(name),
                TCollection_HAsciiString(str(description)),
                # g/cm^3, from kg/m^3. Nought is no density: OCCT then writes none.
                float(density) / 1000.0 if isinstance(density, (int, float)) and density > 0 else 0.0,
                TCollection_HAsciiString("density"),
                TCollection_HAsciiString("POSITIVE_RATIO_MEASURE"),
            )
        self.material_tool.SetMaterial(label, self._materials[name])

    def write(self, path, write_pcurves=True, precision_mode=0, comment=None) -> None:
        """Transfer the document and write it to 'path', named and with PartCAD's attributes on its products."""
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.Interface import Interface_Static
        from OCP.STEPCAFControl import STEPCAFControl_Writer
        from OCP.STEPControl import STEPControl_AsIs

        self.shape_tool.UpdateAssemblies()
        writer = STEPCAFControl_Writer()
        writer.SetColorMode(True)
        writer.SetNameMode(True)
        writer.SetMaterialMode(True)
        Interface_Static.SetIVal_s("write.surfacecurve.mode", 1 if write_pcurves else 0)
        Interface_Static.SetIVal_s("write.precision.mode", int(precision_mode))
        if not writer.Transfer(self.document, STEPControl_AsIs):
            raise ValueError("Failed to transfer the shape to STEP: %s" % path)
        model = writer.ChangeWriter().Model()
        self._finish(model)
        if comment:
            _set_comment(model, comment)
        if writer.Write(path) != IFSelect_RetDone:
            raise ValueError("Failed to write STEP file: %s" % path)

    def _finish(self, model) -> None:
        """Give every product and component its name, and every part's product its PARTCAD_ATTRIBUTE."""
        from OCP.StepBasic import StepBasic_Product
        from OCP.StepRepr import StepRepr_NextAssemblyUsageOccurrence, StepRepr_ProductDefinitionShape
        from OCP.TCollection import TCollection_HAsciiString

        def found(value):
            return self._names.get(value.ToCString()) if value is not None else None

        products, occurrences, attributes = [], [], []
        for index in range(1, model.NbEntities() + 1):
            entity = model.Value(index)
            if isinstance(entity, StepRepr_ProductDefinitionShape):
                # The shape of a product's definition, found by the token its
                # product still has, before any is renamed. The attribute goes
                # on it rather than on the definition itself: OCCT's reader
                # takes every descriptive item on a product definition's
                # properties for the name of its material.
                definition = entity.Definition().ProductDefinition()
                formation = definition.Formation() if definition is not None else None
                product = formation.OfProduct() if formation is not None else None
                entry = found(product.Name()) if product is not None else None
                if entry is not None and entry[1] is not None:
                    attributes.append((entity, entry[1]))
            elif isinstance(entity, StepBasic_Product):
                products.append(entity)
            elif isinstance(entity, StepRepr_NextAssemblyUsageOccurrence):
                occurrences.append(entity)
        for product in products:
            entry = found(product.Name())
            if entry is not None:
                product.SetName(TCollection_HAsciiString(entry[0]))
                product.SetId(TCollection_HAsciiString(entry[0]))
        for occurrence in occurrences:
            entry = found(occurrence.Name())
            if entry is not None:
                occurrence.SetName(TCollection_HAsciiString(entry[0]))
        context = _attribute_context() if attributes else None
        for definition, text in attributes:
            _add_attribute(model, definition, PARTCAD_ATTRIBUTE, text, context)


def _attribute_context():
    from OCP.StepRepr import StepRepr_RepresentationContext
    from OCP.TCollection import TCollection_HAsciiString

    context = StepRepr_RepresentationContext()
    context.Init(TCollection_HAsciiString(""), TCollection_HAsciiString(""))
    return context


def _add_attribute(model, definition, name, value, context) -> None:
    """A user-defined attribute 'name' = 'value' on a product's shape, as the CAx-IF practice writes one.

    A 'PROPERTY_DEFINITION' named 'name' of the 'PRODUCT_DEFINITION_SHAPE'
    'definition', a 'GENERAL_PROPERTY' and its association around it, and a
    'REPRESENTATION' of one 'DESCRIPTIVE_REPRESENTATION_ITEM' holding 'value':
    the form OCCT's reader turns into a 'TDataStd_NamedData' entry on the
    product's label, under the property definition's name, holding the item's
    description. A property with no general property - all a material is
    written as - it does not read as an attribute.
    """
    from OCP.StepBasic import StepBasic_GeneralProperty, StepBasic_GeneralPropertyAssociation
    from OCP.StepRepr import (
        StepRepr_CharacterizedDefinition,
        StepRepr_DescriptiveRepresentationItem,
        StepRepr_HArray1OfRepresentationItem,
        StepRepr_PropertyDefinition,
        StepRepr_PropertyDefinitionRepresentation,
        StepRepr_RepresentedDefinition,
        StepRepr_Representation,
    )
    from OCP.TCollection import TCollection_HAsciiString

    def text(value):
        return TCollection_HAsciiString(value)

    characterized = StepRepr_CharacterizedDefinition()
    characterized.SetValue(definition)
    property_definition = StepRepr_PropertyDefinition()
    property_definition.Init(text(name), False, text(""), characterized)
    item = StepRepr_DescriptiveRepresentationItem()
    item.Init(text(name), text(value))
    items = StepRepr_HArray1OfRepresentationItem(1, 1)
    items.SetValue(1, item)
    representation = StepRepr_Representation()
    representation.Init(text(USER_DEFINED_ATTRIBUTES), items, context)
    represented = StepRepr_RepresentedDefinition()
    represented.SetValue(property_definition)
    property_representation = StepRepr_PropertyDefinitionRepresentation()
    property_representation.Init(represented, representation)
    general = StepBasic_GeneralProperty()
    general.Init(text(""), text(USER_DEFINED_ATTRIBUTES), False, text(""))
    association = StepBasic_GeneralPropertyAssociation()
    association.Init(text(""), text(""), general, property_definition)
    model.AddWithRefs(property_representation)
    model.AddWithRefs(association)


def _set_comment(model, comment) -> None:
    """Put 'comment' into the STEP file's FILE_DESCRIPTION header entity.

    ISO 10303-21 has no free-form comment field; the closest thing a reader
    will show is the description carried by the exchange file's header, which
    is what a STEP "comment" conventionally means. Setting it has to happen
    after the transfer -- that is when the writer populates the model whose
    header this rewrites -- and before the file is written.
    """
    from OCP.APIHeaderSection import APIHeaderSection_MakeHeader
    from OCP.TCollection import TCollection_HAsciiString

    header = APIHeaderSection_MakeHeader(model)
    if not header.IsDone():
        raise Exception("Failed to access the STEP header to write the comment")
    header.SetDescriptionValue(1, TCollection_HAsciiString(str(comment)))


def write(path, shape, section=None, name=None):
    """Write 'shape' to a STEP file at 'path' with the colours, the material and the references 'section' gives it.

    One product, through 'Writer', so that a part taken out of an assembly
    ('pc import') keeps what its file said of it. 'section' is in
    'TopExp::MapShapes' order of 'shape' unplaced: a shape with a placement of
    its own is its unplaced product, placed - the same faces, in the same order.
    'name' is the product's, the file's stem by default.
    """
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopTools import TopTools_IndexedMapOfShape

    writer = Writer()
    definition = shape.Located(TopLoc_Location())
    face_sets = solid_sets = None
    if section is not None:
        counts = []
        for kind in (TopAbs_FACE, TopAbs_SOLID):
            found = TopTools_IndexedMapOfShape()
            TopExp.MapShapes_s(definition, kind, found)
            counts.append(found.Extent())
        if len(section.faces) in (0, counts[0]):
            face_sets = [section.face_set(index) for index in range(counts[0])]
        if len(section.solids) in (0, counts[1]):
            solid_sets = [section.solid_set(index) for index in range(counts[1])]
        if solid_sets == [] and section.own() is not None:
            solid_sets = [section.own()]
    if name is None:
        name = os.path.splitext(os.path.basename(path))[0]
    label = writer.part(definition, name, face_sets, solid_sets)
    if not shape.Location().IsIdentity():
        root = writer.assembly(name)
        writer.place(root, label, shape.Location())
    writer.write(path)


def _unlocated_key(shape):
    from OCP.TopLoc import TopLoc_Location

    return shape.Located(TopLoc_Location())


def _attribute(label, guid):
    """The attribute of 'label' with the ID 'guid', or None.

    Found by iterating the label's attributes, as 'wrapper_import_assy' reads a
    name: 'TDF_Label::FindAttribute' fills a handle argument in place, which
    from Python is a freshly made attribute object, and on some files that ends
    in a crash rather than an answer.
    """
    from OCP.TDF import TDF_AttributeIterator

    if label.IsNull():
        return None
    iterator = TDF_AttributeIterator(label)
    while iterator.More():
        attribute = iterator.Value()
        if attribute.ID().IsSame(guid):
            return attribute
        iterator.Next()
    return None


def _material_of(label):
    """The name of the material a shape label is made of, or None.

    Followed the way OCCT stores it - a tree node under the material reference
    GUID, whose father is the label carrying the 'XCAFDoc_Material' - rather
    than through 'XCAFDoc_MaterialTool::GetMaterial', whose strings come back
    through handle arguments a Python caller never sees filled in.
    """
    from OCP.XCAFDoc import XCAFDoc, XCAFDoc_Material

    node = _attribute(label, XCAFDoc.MaterialRefGUID_s())
    if node is None or not hasattr(node, "HasFather") or not node.HasFather():
        return None
    material = _attribute(node.Father().Label(), XCAFDoc_Material.GetID_s())
    if material is None or not hasattr(material, "GetName"):
        return None
    name = material.GetName()
    text = name.ToCString().strip() if name is not None else ""
    return text or None
