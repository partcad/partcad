#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to read a STEP assembly and split it into parts + an assembly tree, so the core
# process never has to touch a live OCP object (nor OCCT's STEP-CAF reader) to
# import an assembly. It parses the XDE tree, zeroes each part's placement, writes
# the parts out as STEP files into 'output_folder', and returns a plain-data tree
# the core turns into an .assy file. Deduplication (by bounding box + volume) and
# the OCCT work all happen here; the core only registers the parts and writes YAML.

import math
import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize. Without this the standard
# library's pyexpat binds to VTK's older expat and any later xml.dom use dies
# with an undefined-symbol ImportError.
import pyexpat  # noqa: F401

from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.TDF import TDF_LabelSequence, TDF_Label, TDF_AttributeIterator
from OCP.TDataStd import TDataStd_Name
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDocStd import TDocStd_Document

from OCP.TopoDS import TopoDS_Shape
from OCP.gp import gp_Trsf
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp

from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID

sys.path.append(os.path.dirname(__file__))
import wrapper_common

# signature -> path of the STEP file written for the first shape with it. A later
# shape whose signature matches reuses that file rather than writing a new one.
_shape_cache = {}


def get_label_name(label: TDF_Label, default="Unnamed") -> str:
    """Extracts the name from a label if available, otherwise returns the default name."""
    if label.IsNull():
        return default
    iterator = TDF_AttributeIterator(label)
    while iterator.More():
        attr = iterator.Value()
        # OCP 7.9 dropped the static Standard_GUID.IsEqual_s in favour of the
        # instance method IsSame, which compares the same way.
        if attr.ID().IsSame(TDataStd_Name.GetID_s()):
            return attr.Get().ToExtString()
        iterator.Next()
    return default


def clone_transformation(src: gp_Trsf) -> gp_Trsf:
    """Creates a deep copy of a gp_Trsf transformation matrix."""
    new_trsf = gp_Trsf()
    new_trsf.SetValues(
        src.Value(1, 1), src.Value(1, 2), src.Value(1, 3), src.Value(1, 4),
        src.Value(2, 1), src.Value(2, 2), src.Value(2, 3), src.Value(2, 4),
        src.Value(3, 1), src.Value(3, 2), src.Value(3, 3), src.Value(3, 4)
    )
    return new_trsf


def invert_transformation(src: gp_Trsf) -> gp_Trsf:
    """Returns the inverse of a transformation matrix."""
    inverted_trsf = clone_transformation(src)
    inverted_trsf.Invert()
    return inverted_trsf


def transformation_difference(t1: gp_Trsf, t2: gp_Trsf) -> float:
    """Computes the maximum absolute difference between corresponding matrix elements."""
    return max(
        abs(t1.Value(row, col) - t2.Value(row, col))
        for row in range(1, 4)
        for col in range(1, 5)
    )


def combine_transformations(parent: gp_Trsf, local: gp_Trsf, tolerance=1e-7) -> gp_Trsf:
    """
    Computes the resulting transformation by applying parent * local.
    If the difference between (parent * local) and local is below the tolerance,
    returns local, assuming it already includes the parent transformation.
    """
    combined_trsf = gp_Trsf()
    combined_trsf.Multiply(parent)
    combined_trsf.Multiply(local)

    return clone_transformation(local if transformation_difference(combined_trsf, local) < tolerance else combined_trsf)


def convert_location(trsf: gp_Trsf, precision=5):
    """
    Converts a transformation into a format: [[tx, ty, tz], [ax, ay, az], angle],
    with rounded values to the specified precision.
    """
    translation = [
        round(trsf.TranslationPart().X(), precision),
        round(trsf.TranslationPart().Y(), precision),
        round(trsf.TranslationPart().Z(), precision)
    ]

    quaternion = trsf.GetRotation()
    w, x, y, z = quaternion.W(), quaternion.X(), quaternion.Y(), quaternion.Z()

    norm = math.sqrt(w*w + x*x + y*y + z*z)
    if norm < 1e-6:
        return [translation, [1.0, 0.0, 0.0], 0.0]

    rotation_angle = 2.0 * math.atan2(math.sqrt(x**2 + y**2 + z**2), w)
    rotation_angle_deg = round(math.degrees(rotation_angle), precision)

    sin_half_angle = math.sin(rotation_angle / 2.0)
    if abs(sin_half_angle) < 1e-6:
        rotation_axis = [1.0, 0.0, 0.0]
    else:
        rotation_axis = [
            round(x / sin_half_angle, precision),
            round(y / sin_half_angle, precision),
            round(z / sin_half_angle, precision)
        ]

    return [translation, rotation_axis, rotation_angle_deg]


def save_shape_to_step(shape: TopoDS_Shape, filename: str):
    """Saves a TopoDS_Shape to a STEP file."""
    writer = STEPControl_Writer()
    if writer.Transfer(shape, STEPControl_AsIs) != 1 or writer.Write(filename) != 1:
        raise ValueError(f"Failed to write STEP file: {filename}")


def shape_signature(shape: TopoDS_Shape) -> tuple:
    """Computes a unique signature for a shape based on its bounding box and volume."""
    bbox = Bnd_Box()
    BRepBndLib.Add_s(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    volume = props.Mass()

    return tuple(round(v, 5) for v in (xmin, ymin, zmin, xmax, ymax, zmax, volume))


def parse_label_recursive(label, shape_tool, parent_trsf: gp_Trsf, visited):
    """
    Recursively traverses the XDE tree:
      - If it's an Assembly, processes child components.
      - If it's a simple shape or a compound with a single solid, creates a part.
      - If it's a compound with multiple solids, splits it into a sub-assembly.
    """
    if label in visited:
        return None
    visited.add(label)

    # Compute transformation
    local_trsf = shape_tool.GetLocation_s(label).Transformation()
    combined_trsf = combine_transformations(parent_trsf, local_trsf, tolerance=1e-7)

    name = get_label_name(label, default="Unnamed")

    # Handle Assembly
    if shape_tool.IsAssembly_s(label):
        node = {"type": "assembly", "name": name, "trsf": combined_trsf, "children": []}

        child_labels = TDF_LabelSequence()
        shape_tool.GetComponents_s(label, child_labels)

        for i in range(child_labels.Length()):
            child_label = child_labels.Value(i + 1)
            child_node = parse_label_recursive(child_label, shape_tool, combined_trsf, visited)
            if child_node:
                node["children"].append(child_node)

        return node

    # Handle Simple Shape
    shape = shape_tool.GetShape_s(label)
    if shape_tool.IsSimpleShape_s(label) and not shape.IsNull():
        return {"type": "part", "name": name, "shape": shape, "trsf": combined_trsf}

    # Handle Compound (multi-solid)
    if not shape.IsNull():
        solids = []
        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        while explorer.More():
            solids.append(explorer.Current())
            explorer.Next()

        if len(solids) > 1:
            child_nodes = []

            for idx, solid in enumerate(solids, start=1):
                solid_trsf = combine_transformations(combined_trsf, solid.Location().Transformation(), tolerance=1e-7)
                child_nodes.append({"type": "part", "name": f"{name}_solid{idx}", "shape": solid, "trsf": solid_trsf})

            return {"type": "assembly", "name": name, "trsf": combined_trsf, "children": child_nodes}

        else:
            return {"type": "part", "name": name, "shape": shape, "trsf": combined_trsf}

    return None


def parse_step_tree(step_file: str):
    """Reads a STEP file and returns a hierarchical structure of its components."""
    if not os.path.isfile(step_file):
        raise FileNotFoundError(step_file)

    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("XDE-doc"))
    app.NewDocument(TCollection_ExtendedString("XmlXCAF"), doc)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    reader = STEPCAFControl_Reader()
    if reader.ReadFile(step_file) != IFSelect_RetDone or reader.Transfer(doc) != 1:
        raise ValueError(f"Failed to read STEP file: {step_file}")

    root_nodes = []
    free_shapes = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_shapes)
    identity_trsf = gp_Trsf()

    for i in range(free_shapes.Length()):
        label = free_shapes.Value(i + 1)
        root_nodes.append(parse_label_recursive(label, shape_tool, identity_trsf, set()))

    return root_nodes


def parse_assembly_tree(assembly_file: str, file_type: str):
    """Parses an assembly file into a hierarchical structure based on its format.

    Supported file types:
      - "step"/"stp": Uses the STEP reader (`parse_step_tree`)
    """
    file_type = file_type.lower()
    if file_type in ["step", "stp"]:
        return parse_step_tree(assembly_file)
    raise ValueError(f"Unsupported assembly file type: {file_type}")


def flatten_assembly_tree(node, output_folder: str, precision: int):
    """Converts a hierarchical assembly tree into flat data, writing STEP files.

    Assembly nodes become '{"type": "assembly", "name", "links": [...]}'. Part
    nodes have their placement zeroed out, are written to a STEP file under
    'output_folder' (deduplicated by signature), and become
    '{"type": "part", "name", "part_file", "location"}'. The core resolves
    'part_file' to a registered part name and builds the .assy from this tree.
    """
    node_type = node["type"]
    node_name = node["name"]
    global_trsf = node["trsf"]

    if node_type == "assembly":
        return {
            "type": "assembly",
            "name": node_name,
            "links": [flatten_assembly_tree(ch, output_folder, precision) for ch in node.get("children", [])],
        }

    shape = node["shape"]
    zeroed_shape = BRepBuilderAPI_Transform(shape, invert_transformation(global_trsf), True).Shape()
    signature = shape_signature(zeroed_shape)

    if signature in _shape_cache:
        part_file = _shape_cache[signature]
    else:
        # 'import_part' used Path(part_name).name for the file name, so any path
        # separator a STEP label carried is dropped from the file on disk.
        file_safe_name = os.path.basename(node_name)
        part_file = os.path.join(output_folder, f"{file_safe_name}.step")
        save_shape_to_step(zeroed_shape, part_file)
        _shape_cache[signature] = part_file

    return {
        "type": "part",
        "name": node_name,
        "part_file": part_file,
        "location": convert_location(global_trsf, precision),
    }


def process(request):
    assembly_file = request["assembly_file"]
    file_type = request["file_type"]
    assembly_name = request["assembly_name"]
    output_folder = request["output_folder"]
    precision = request.get("precision", 5)

    _shape_cache.clear()

    root_nodes = parse_assembly_tree(assembly_file, file_type)
    if not root_nodes or all(node is None for node in root_nodes):
        raise ValueError(f"No shapes found in {assembly_file}")
    root_nodes = [node for node in root_nodes if node is not None]

    # If multiple root nodes exist, wrap them in a synthetic top-level assembly.
    if len(root_nodes) > 1:
        final_structure = {
            "type": "assembly",
            "name": f"{assembly_name}_top",
            "trsf": gp_Trsf(),
            "children": root_nodes,
        }
    else:
        final_structure = root_nodes[0]

    return flatten_assembly_tree(final_structure, output_folder, precision)


if __name__ == "__main__":
    # argv[1] carries the operation name for readability in process listings; the
    # authoritative request travels via stdin.
    _, request = wrapper_common.handle_input()
    try:
        root = process(request)
        model = {"success": True, "exception": None, "root": root}
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "root": None}
    wrapper_common.handle_output(model)
