import math
from pathlib import Path
import yaml

from OCP.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopoDS import TopoDS_Shape
from OCP.gp import gp_Trsf
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDF import TDF_LabelSequence
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDocStd import TDocStd_Document

from partcad.actions.part_actions import import_part_action
import partcad.logging as pc_logging
from partcad.project import Project


def _convert_location(trsf: gp_Trsf):
    """
    Convert a gp_Trsf into the format [translation, rotation_axis, rotation_angle].
    translation: [tx, ty, tz]
    rotation_axis: [rx, ry, rz]
    rotation_angle: angle in radians
    """
    translation = [
        trsf.TranslationPart().X(),
        trsf.TranslationPart().Y(),
        trsf.TranslationPart().Z()
    ]
    quaternion = trsf.GetRotation()
    w, x, y, z = quaternion.W(), quaternion.X(), quaternion.Y(), quaternion.Z()
    rotation_angle = 2.0 * math.acos(w)
    sin_half_angle = math.sqrt(max(0.0, 1.0 - w * w))
    if sin_half_angle < 1e-6:
        rotation_axis = [1.0, 0.0, 0.0]
        rotation_angle = 0.0
    else:
        rotation_axis = [x / sin_half_angle, y / sin_half_angle, z / sin_half_angle]
    return [translation, rotation_axis, rotation_angle]


def _save_shape_to_step(shape: TopoDS_Shape, filename: str):
    """
    Save the given shape (with its Location) to a STEP file.
    Logs info on success; raises ValueError if transfer or write fails.
    """
    writer = STEPControl_Writer()
    status = writer.Transfer(shape, STEPControl_AsIs)
    if status != 1:
        raise ValueError(f"Failed to transfer shape to STEP file: {filename}")
    status = writer.Write(filename)
    if status != 1:
        raise ValueError(f"Failed to save STEP file: {filename}")
    pc_logging.info(f"Saved shape to STEP file: {filename}")


def get_bbox_key(shape: TopoDS_Shape):
    """
    Compute the bounding box of the shape and return a tuple of rounded coordinates.
    Used for duplicate filtering.
    """
    box = Bnd_Box()
    try:
        # Use optimized Add_s if available
        BRepBndLib.Add_s(shape, box)
    except AttributeError:
        BRepBndLib.Add(shape, box)
    return tuple(round(v, 3) for v in box.Get())


def filter_unique_parts(parts):
    """
    Filters duplicates based on unique TShape and transformation.
    A composite key is formed as:
       (tshape_id, translation, rotation_axis, rotation_angle)
    Duplicate entries (with matching key) are discarded.
    """
    unique = {}
    for shape, trsf in parts:
        try:
            tshape_id = shape.TShape().__long__()
        except Exception:
            tshape_id = id(shape)
        trans = _convert_location(trsf)
        trans_key = tuple(round(v, 3) for v in trans[0])
        rot_key = tuple(round(v, 3) for v in trans[1])
        angle_key = round(trans[2], 3)
        key = (tshape_id, trans_key, rot_key, angle_key)
        if key not in unique:
            unique[key] = (shape, trsf)
    return list(unique.values())


def parse_step_file(file_path: str):
    """
    Read a STEP file via XDE using free shapes only.
    If only one free shape is found, check its content:
      - If it contains >1 SOLID, split it into separate parts.
      - Otherwise, return as is.
    """
    pc_logging.info(f"=== Trying XDE approach for file: {file_path} ===")
    xde_parts = read_xde_assembly_top_level(file_path)
    if xde_parts:
        unique_parts = filter_unique_parts(xde_parts)
        if len(unique_parts) == 1:
            shape, trsf = unique_parts[0]
            explorer = TopExp_Explorer(shape, TopAbs_SOLID)
            parts_list = []
            while explorer.More():
                solid = explorer.Current()
                parts_list.append((solid, trsf))
                explorer.Next()
            if len(parts_list) > 1:
                is_assembly = True
                unique_parts = parts_list
            else:
                is_assembly = False
        else:
            is_assembly = (len(unique_parts) > 1)
        pc_logging.info(f"XDE approach found {len(unique_parts)} unique part(s).")
        return (is_assembly, unique_parts)
    else:
        pc_logging.info("XDE approach returned no parts. Falling back to direct STEP parse.")
        return parse_step_file_fallback(file_path)


def parse_step_file_fallback(file_path: str):
    """
    Classic approach using TransferRoots() and OneShape().
    Extracts SOLIDs and their Locations from the STEP file.
    """
    reader = STEPControl_Reader()
    status = reader.ReadFile(file_path)
    if status != 1:
        raise ValueError(f"Invalid STEP file: {file_path}")

    reader.TransferRoots()
    shape = reader.OneShape()
    pc_logging.info(f"=== parse_step_file_fallback ===\nSTEP file: {file_path}")

    parts = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        solid = explorer.Current()
        trsf = solid.Location().Transformation()
        parts.append((solid, trsf))
        explorer.Next()

    is_assembly = (len(parts) > 1)
    return (is_assembly, parts)


def read_xde_assembly_top_level(file_path: str):
    """
    Read a STEP file via XDE, retrieving only the free shapes (top-level).
    No recursive traversal of sub-components.
    Returns a list of (TopoDS_Shape, gp_Trsf).
    """
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    app.NewDocument(TCollection_ExtendedString("XmlXCAF"), doc)

    reader = STEPCAFControl_Reader()
    if reader.ReadFile(file_path) != 1:
        return []

    # Transfer STEP data into the XDE document
    reader.Transfer(doc)

    # Get the ShapeTool and free shapes from the document
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    free_labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_labels)

    result = []
    for i in range(free_labels.Length()):
        lbl = free_labels.Value(i + 1)
        loc = shape_tool.GetLocation_s(lbl)  # Returns TopLoc_Location
        shape = shape_tool.GetShape_s(lbl)
        if not shape.IsNull():
            result.append((shape, loc.Transformation()))
    return result


def explore_xde_label(label, shape_tool, parent_trsf: gp_Trsf, visited, results):
    """
    Recursively traverse the XDE tree using GetComponents_s.
    For each label:
      - Get the local transformation.
      - Compute combined_trsf = parent_trsf * current_trsf.
      - If the label contains a shape, add (shape, combined_trsf) to results.
      - Recursively traverse child components.
    """
    if label in visited:
        return
    visited.add(label)

    loc = shape_tool.GetLocation_s(label)
    current_trsf = loc.Transformation()
    combined_trsf = gp_Trsf()
    combined_trsf.Multiply(parent_trsf)
    combined_trsf.Multiply(current_trsf)

    shape = shape_tool.GetShape_s(label)
    if not shape.IsNull():
        results.append((shape, combined_trsf))

    from OCP.TDF import TDF_LabelSequence
    children = TDF_LabelSequence()
    shape_tool.GetComponents_s(label, children)
    for i in range(children.Length()):
        child_lbl = children.Value(i + 1)
        explore_xde_label(child_lbl, shape_tool, combined_trsf, visited, results)


def parse_assembly_file(file_type: str, file_path: str):
    """
    Parse an assembly file based on its type.
    Currently supports only STEP files.
    """
    if file_type.lower() == "step":
        return parse_step_file(file_path)
    else:
        raise ValueError(f"Unsupported assembly file type: {file_type}")


def import_assy_action(project: Project, file_type: str, assembly_file: str, config: dict):
    """
    Main function for importing an assembly:
      - Read the STEP file (via XDE or fallback).
      - Save each SOLID with its applied transformation as a separate STEP file.
      - Write assembly data (part names and locations) into a YAML file.
    """
    name = Path(assembly_file).stem
    is_assembly, parts_data = parse_assembly_file(file_type, assembly_file)
    if not is_assembly:
        pc_logging.error(f"File '{assembly_file}' does not contain an assembly.")
        raise ValueError(f"File '{assembly_file}' does not contain an assembly.")

    pc_logging.info(f"Detected an assembly with {len(parts_data)} parts.")
    assy_folder_path = Path(assembly_file).parent / name
    assy_folder_path.mkdir(parents=True, exist_ok=True)
    pc_logging.info(f"Saving parts in folder: {assy_folder_path}")

    part_names = []
    part_files = []
    part_locations = []

    for i, (moved_solid, trsf) in enumerate(parts_data, start=1):
        part_name = f"{name}_part{i}"
        part_file = assy_folder_path / f"{part_name}.step"
        part_file_without_ext = assy_folder_path / f"{part_name}"

        _save_shape_to_step(moved_solid, str(part_file))
        import_part_action(
            project,
            file_type,
            part_name,
            str(part_file),
            config,
            target_dir=str(assy_folder_path)
        )
        part_names.append(part_name)
        part_files.append(part_file_without_ext)

        location_data = _convert_location(trsf)
        part_locations.append(location_data)

        pc_logging.info(f"Imported part: {part_name} → {part_file}")
        pc_logging.info(f"  Location: {location_data}")

    assy_name = f"{name}_assy"
    assy_file_path = assy_folder_path / f"{assy_name}.assy"

    assy_data = {
        "name": assy_name,
        "description": config.get("desc", ""),
        "links": [
            {"part": str(part_name), "location": loc}
            for part_name, loc in zip(part_files, part_locations)
        ],
    }

    with open(assy_file_path, "w") as assy_file:
        yaml.dump(assy_data, assy_file, default_flow_style=False)

    success = project.add_assembly("assy", str(assy_file_path), config)
    if not success:
        pc_logging.error(f"Failed to add assembly '{assy_name}'.")
        raise ValueError(f"Failed to add assembly '{assy_name}'.")

    pc_logging.info(f"Assembly '{assy_name}' successfully added with {len(part_names)} parts.")
    return assy_name
