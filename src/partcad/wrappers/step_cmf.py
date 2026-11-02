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
"""

import ocp_serialize

ORIGIN = "raw:step"

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
        # '(shape, name)' for every product made of a material.
        self.materials = []
        for r in range(1, roots.Length() + 1):
            for label in _labels(shape_tool, roots.Value(r)):
                material = _material_of(label)
                if material:
                    self.materials.append((XCAFDoc_ShapeTool.GetShape_s(label), material))
                if XCAFDoc_ShapeTool.IsAssembly_s(label):
                    continue
                own = XCAFPrs_IndexedDataMapOfShapeStyle()
                XCAFPrs.CollectStyleSettings_s(label, TopLoc_Location(), own)
                for index in range(1, own.Extent() + 1):
                    color = _color(own.FindFromIndex(index))
                    if color is not None:
                        self.definition_colors.append((own.FindKey(index), color))
        self.definition_colors.sort(key=lambda pair: _rank(pair[0]))

    def __bool__(self):
        return bool(self.colors or self.definition_colors or self.materials)


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

    if not face_colors and not solid_colors and not solid_materials:
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


def write(path, shape, section=None):
    """Write 'shape' to a STEP file at 'path' with the colours and the material 'section' gives it.

    Through XCAF, so that a part taken out of an assembly keeps what its file
    said of it: each face's colour as a style of that face, and a material on
    the product where every solid of it is made of the same one (STEP states a
    material per product, which is where OCCT writes it).
    """
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TCollection import TCollection_ExtendedString, TCollection_HAsciiString
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.TDF import TDF_Label
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    document = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    XCAFApp_Application.GetApplication_s().NewDocument(TCollection_ExtendedString("MDTV-XCAF"), document)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    label = shape_tool.AddShape(shape, False)
    # A shape with a placement of its own is added as a reference to the
    # unplaced one, and what is said of its faces is said of that one's: the
    # same faces, in the same order.
    base = shape
    if XCAFDoc_ShapeTool.IsReference_s(label):
        referred = TDF_Label()
        if XCAFDoc_ShapeTool.GetReferredShape_s(label, referred):
            label = referred
            base = XCAFDoc_ShapeTool.GetShape_s(referred)
    if section is not None:
        faces = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(base, TopAbs_FACE, faces)
        if len(section.faces) in (0, faces.Extent()):
            for index in range(faces.Extent()):
                rgba = section.face_set(index).rgba
                if rgba is None:
                    continue
                sub = shape_tool.AddSubShape(label, faces.FindKey(index + 1))
                if not sub.IsNull():
                    color_tool.SetColor(sub, _quantity(rgba), XCAFDoc_ColorSurf)
        solids = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(base, TopAbs_SOLID, solids)
        materials = {section.solid_set(index).material for index in range(solids.Extent())} or {
            getattr(section.own(), "material", None)
        }
        materials.discard(None)
        if len(materials) == 1:
            material_tool = XCAFDoc_DocumentTool.MaterialTool_s(document.Main())
            name = TCollection_HAsciiString(materials.pop())
            empty = TCollection_HAsciiString("")
            material_tool.SetMaterial(
                label, material_tool.AddMaterial(name, empty, 0.0, TCollection_HAsciiString("density"), empty)
            )
    writer = STEPCAFControl_Writer()
    writer.SetColorMode(True)
    writer.SetNameMode(True)
    if not writer.Transfer(document, STEPControl_AsIs) or writer.Write(path) != IFSelect_RetDone:
        raise ValueError("Failed to write STEP file: %s" % path)


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
