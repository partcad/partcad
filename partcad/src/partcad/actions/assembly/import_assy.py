import os
import math
from pathlib import Path
import yaml

from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.TDF import TDF_LabelSequence, TDF_Label, TDF_AttributeIterator
from OCP.TDataStd import TDataStd_Name
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDocStd import TDocStd_Document
from OCP.Standard import Standard_GUID

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

import partcad.logging as pc_logging
from partcad.actions.part import import_part_action
from partcad.project import Project

shape_cache = {}


def get_label_name(label: TDF_Label, default="Unnamed") -> str:
    """Extracts the name from a label if available, otherwise returns the default name."""
    if label.IsNull():
        return default
    iterator = TDF_AttributeIterator(label)
    while iterator.More():
        attr = iterator.Value()
        if Standard_GUID.IsEqual_s(attr.ID(), TDataStd_Name.GetID_s()):
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


def convert_location(trsf: gp_Trsf):
    """
    Converts a transformation into a format: [[tx, ty, tz], [ax, ay, az], angle].
    """
    translation = [trsf.TranslationPart().X(), trsf.TranslationPart().Y(), trsf.TranslationPart().Z()]

    quaternion = trsf.GetRotation()
    w, x, y, z = quaternion.W(), quaternion.X(), quaternion.Y(), quaternion.Z()
    rotation_angle = 2.0 * math.atan2(math.sqrt(x**2 + y**2 + z**2), w)
    rotation_angle_deg = math.degrees(rotation_angle)

    sin_half_angle = math.sin(rotation_angle / 2.0)
    rotation_axis = [1.0, 0.0, 0.0] if abs(sin_half_angle) < 1e-6 else [x / sin_half_angle, y / sin_half_angle, z / sin_half_angle]

    return [translation, rotation_axis, rotation_angle_deg]


def save_shape_to_step(shape: TopoDS_Shape, filename: Path):
    """Saves a TopoDS_Shape to a STEP file."""
    filename = filename.resolve(strict=False)

    writer = STEPControl_Writer()
    if writer.Transfer(shape, STEPControl_AsIs) != 1 or writer.Write(str(filename)) != 1:
        raise ValueError(f"Failed to write STEP file: {filename}")


def import_part(project: Project, shape: TopoDS_Shape, part_name: str, parent_folder: Path, config: dict) -> str:
    """Saves shape as STEP and imports it into the project."""

    project_root = Path.cwd().resolve()
    parent_folder = (project_root / parent_folder).resolve(strict=False)
    parent_folder.mkdir(parents=True, exist_ok=True)

    step_file = parent_folder / f"{part_name}.step"
    save_shape_to_step(shape, step_file)

    import_part_action(project, "step", part_name.replace("\\", "/"), step_file.as_posix(), config)
    return str(step_file)


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
        pc_logging.info(f"Processing assembly: {name}")
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
        pc_logging.info(f"Processing simple part: {name}")
        return {"type": "part", "name": name, "shape": shape, "trsf": combined_trsf}

    # Handle Compound (multi-solid)
    if not shape.IsNull():
        solids = []
        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        while explorer.More():
            solids.append(explorer.Current())
            explorer.Next()

        pc_logging.info(f"Compound label '{name}': {len(solids)} solid(s) found.")

        if len(solids) > 1:
            pc_logging.info(f"Creating sub-assembly for compound: {name}")
            child_nodes = []

            for idx, solid in enumerate(solids, start=1):
                solid_trsf = combine_transformations(combined_trsf, solid.Location().Transformation(), tolerance=1e-7)
                child_nodes.append({"type": "part", "name": f"{name}_solid{idx}", "shape": solid, "trsf": solid_trsf})

            return {"type": "assembly", "name": name, "trsf": combined_trsf, "children": child_nodes}

        else:
            pc_logging.info(f"Single solid fallback for: {name}")
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


def flatten_assembly_tree(node, parent_folder: Path, project: Project, config: dict, assembly_name: str):
    """Converts a hierarchical assembly tree into a flat structure with STEP files."""
    node_type = node["type"]
    node_name = node["name"]
    global_trsf = node["trsf"]

    full_node_name = f"{assembly_name}/{node_name}".replace("\\", "/")

    if node_type == "assembly":
        return {
            "type": "assembly",
            "name": full_node_name,
            "links": [
                flatten_assembly_tree(ch, parent_folder, project, config, assembly_name)
                for ch in node.get("children", [])
            ],
        }

    shape = node["shape"]
    zeroed_shape = BRepBuilderAPI_Transform(shape, invert_transformation(global_trsf), True).Shape()
    signature = shape_signature(zeroed_shape)

    if signature in shape_cache:
        return {
            "type": "part",
            "name": full_node_name,
            "part": shape_cache[signature].replace("\\", "/"),
            "location": convert_location(global_trsf),
        }

    part_path = import_part(project, zeroed_shape, full_node_name, parent_folder, config)
    shape_cache[signature] = part_path

    return {
        "type": "part",
        "name": full_node_name,
        "part": part_path.replace("\\", "/"),
        "location": convert_location(global_trsf),
    }


def parse_assembly_tree(assembly_file: str, file_type: str):
  """
  Parses an assembly file into a hierarchical structure based on its format.

  Supported file types:
    - "step": Uses STEP reader (`parse_step_tree`)

  Returns:
      List of root nodes in the parsed assembly tree.
  """
  file_type = file_type.lower()

  if file_type in ["step", "stp"]:
      return parse_step_tree(assembly_file)
  else:
      raise ValueError(f"Unsupported assembly file type: {file_type}")



def import_assy_action(
    project: Project,
    file_type: str,
    assembly_file: str,
    config: dict
) -> str:
    """
    Imports an assembly into the project, supporting multiple file formats.

    Steps:
      1) Parses the assembly file into a hierarchical structure based on its format.
      2) Flattens the hierarchy into a single .assy structure, avoiding duplicates.
      3) Saves the .assy file and adds the assembly to the project.

    Supported formats:
      - STEP (.step, .stp)
    """

    file_path = Path(assembly_file)

    if not file_path.exists():
        raise FileNotFoundError(f"File '{assembly_file}' not found.")

    shape_cache.clear()
    pc_logging.info(f"Starting import of assembly: {assembly_file} (Type: {file_type})")

    # Parse the assembly file based on its type
    root_nodes = parse_assembly_tree(assembly_file, file_type)
    if not root_nodes:
        raise ValueError(f"No shapes found in {assembly_file}")

    assembly_name = Path(assembly_file).stem
    output_folder = Path(project.config_dir).resolve() / assembly_name
    output_folder.mkdir(parents=True, exist_ok=True)

    # If multiple root nodes exist, create a top-level assembly
    if len(root_nodes) > 1:
        pc_logging.info(f"Creating a top-level assembly for {len(root_nodes)} root nodes")
        top_node = {
            "type": "assembly",
            "name": f"{assembly_name}_top",
            "trsf": gp_Trsf(),
            "children": root_nodes
        }
        final_structure = top_node
    else:
        final_structure = root_nodes[0]

    # Flatten the hierarchical structure into a single .assy file
    top_data = flatten_assembly_tree(final_structure, output_folder, project, config, assembly_name)
    assy_name = top_data["name"]
    assy_file_path = output_folder / f"{assy_name}.assy"

    # Prepare .assy file data
    assembly_data = {
        "name": top_data["name"],
        "description": config.get("desc", ""),
        "links": top_data.get("links", []) if top_data["type"] == "assembly" else []
    }

    # Save assembly data to YAML format
    with open(assy_file_path, "w") as file:
        yaml.dump(assembly_data, file, default_flow_style=False)

    # Add assembly to the project
    project.add_assembly("assy", str(assy_file_path), config)
    pc_logging.info(f"Successfully created assembly file: {assy_file_path}")

    return assembly_data["name"]
