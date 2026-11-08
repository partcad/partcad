#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in STEP exporter (see '//builtin/export' in partcad.yaml).

Runs inside a PartCAD sandbox, driven by 'wrappers/wrapper_export.py'. It is
handed the shape to write in 'request["wrapped"]', the tree it was decoded from
in 'request["shape_tree"]', and the export parameters declared for 'step' as the
remaining keys of 'request'.

Written from the tree, through OCCT's XCAF writer ('step_cmf.Writer'), so that
the file says what the object is and not only what shape it has
(docs/design/cmf.md, section 9, "Exports"):

- **structure and names**: a product per part and per assembly, named after it,
  and a component per placement, named after the link that placed it. A part
  placed several times is one product placed several times, as a STEP file
  written by a CAD tool has it, and as 'pc import' reads it back;
- **colours**: each face's display, as sRGB, on the product, its solids or its
  faces - whichever says it once;
- **materials**: on the product, by reference, with the description and the
  density the declaration states, which the core resolves and hands over under
  'request["cmf"]' (a declaration is the core's to read, and this runs in a
  sandbox);
- **PartCAD's references** for every face and solid, as a user-defined
  attribute on each part's product: what makes the file read back, as a STEP
  part, as the part it was - the same colour, material and finish references on
  every face and solid (docs/design/cmf.md, 11.6).

A face nobody coloured is written uncoloured, and a part that states no CMF at
all is written as it was before this exporter wrote any - the same geometry, now
in a product of its own name.
"""

import os
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common

# What this implementation reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again. 2: written from the tree through XCAF, with the
# product structure, names, colours, materials and PartCAD's references.
CACHE_VERSION = 2

# The request key the core puts what it resolved of the CMF declarations the
# shapes name under, when this file type declares 'cmf: true' (see
# 'partcad.output.CMF_KEY', its twin).
CMF_KEY = "cmf"


def _name(node, fallback):
    """What a product is called: its object's name without its package, else its label, else 'fallback'."""
    name = node.get("name")
    if isinstance(name, str) and name:
        return name.rpartition(":")[2] or name
    label = node.get("label")
    if isinstance(label, str) and label:
        return label.rpartition("/")[2] or label
    return fallback


def _instance_name(node, fallback):
    """What a component is called: the label the link placed it under, else its product's name."""
    label = node.get("label")
    if isinstance(label, str) and label:
        return label.rpartition("/")[2] or label
    return _name(node, fallback)


def _toploc(packed):
    import ocp_serialize
    from OCP.TopLoc import TopLoc_Location

    return ocp_serialize.toploc_from_packed(packed) if packed is not None else TopLoc_Location()


def write_tree(path, tree, facts=None, warnings=None, **options):
    """Write 'tree' (a 'shape_tree') to the STEP file at 'path'. 'options' are 'step_cmf.Writer.write''s."""
    import appearance
    import cmf_export
    import ocp_serialize
    import step_cmf
    from OCP.TopLoc import TopLoc_Location

    writer = step_cmf.Writer(facts)
    memo = {}

    def add(node, inherited):
        """'(label, location)': the product 'node' is, and where its parent places it."""
        color = appearance.own_color(node, warnings) or inherited
        if ocp_serialize.is_shape_object(node):
            shape = node[ocp_serialize.KEY_SHAPE]
            definition = shape.Located(TopLoc_Location())
            own = cmf_export.face_sets(cmf_export.Leaf(node, None, []), memo, definition)
            face_sets = [cmf_export.with_display(cmf_set, color) for cmf_set in own]
            solid_sets = cmf_export.solid_sets(cmf_export.Leaf(node, None, []), memo, definition)
            payload = node[ocp_serialize.KEY_BREP]
            # One product per geometry and per what it is drawn in: the colour
            # an assembly lends it counts only where its own section leaves a
            # face uncoloured.
            lent = color if any(cmf_set.rgba is None for cmf_set in own) else None
            key = (
                payload if isinstance(payload, (str, bytes)) else bytes(payload),
                node.get(ocp_serialize.KEY_CHILD),
                lent,
            )
            label = writer.part(definition, _name(node, "part"), face_sets, solid_sets, key)
            # Where 'ocp_serialize.decode_tree' puts it: at the node's location
            # where it has one, else where its geometry already is.
            packed = node.get(ocp_serialize.KEY_LOCATION)
            return label, _toploc(packed) if packed is not None else shape.Location()
        label = writer.assembly(_name(node, "assembly"))
        for child in node.get(ocp_serialize.KEY_ASSEMBLY) or []:
            if not isinstance(child, dict):
                continue
            child_label, location = add(child, color)
            writer.place(label, child_label, location, _instance_name(child, "component"))
        return label, _toploc(node.get(ocp_serialize.KEY_LOCATION))

    label, location = add(tree, None)
    if not location.IsIdentity():
        # The object itself placed somewhere: an assembly of it, placed there,
        # so that the file's geometry is where the object's is.
        root = writer.assembly(_name(tree, "assembly"))
        writer.place(root, label, location, _instance_name(tree, "component"))
    writer.write(path, **options)


def process(path, request):
    try:
        import ocp_serialize

        tree = request.get("shape_tree")
        if not (ocp_serialize.is_shape_object(tree) or ocp_serialize.is_assembly_object(tree)):
            wrapped = request.get("wrapped")
            if wrapped is None:
                raise ValueError("The STEP exporter needs a shape or an assembly to export")
            # Handed the geometry alone: one product of it, with nothing said.
            tree = {ocp_serialize.KEY_BREP: b"", ocp_serialize.KEY_SHAPE: wrapped, "name": request.get("shape_name")}
        facts = request.get(CMF_KEY)
        warnings = []
        write_tree(
            path,
            tree,
            facts if isinstance(facts, dict) else None,
            warnings,
            write_pcurves=bool(request.get("write_pcurves", True)),
            precision_mode=request.get("precision_mode", 0),
            comment=request.get("comment"),
        )

        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception(f"Failed to create STEP file: {path}")

        return {"success": True, "exception": None, "files": [], "warnings": warnings}

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
