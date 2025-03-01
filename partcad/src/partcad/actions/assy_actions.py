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
from partcad.actions.part_actions import import_part_action
from partcad.project import Project

g_shape_map = {}

def get_label_name(label: TDF_Label, default="Unnamed") -> str:
    """Get the TDataStd_Name attribute from a label."""
    if label.IsNull():
        return default
    it = TDF_AttributeIterator(label)
    while it.More():
        attr = it.Value()
        if Standard_GUID.IsEqual_s(attr.ID(), TDataStd_Name.GetID_s()):
            pc_logging.debug(f"[DEBUG] Found name: {attr.Get().ToExtString()}")
            return attr.Get().ToExtString()
        it.Next()
    return default

def clone_trsf(src: gp_Trsf) -> gp_Trsf:
    """Clone a gp_Trsf matrix."""
    new_trsf = gp_Trsf()
    new_trsf.SetValues(
        src.Value(1,1), src.Value(1,2), src.Value(1,3), src.Value(1,4),
        src.Value(2,1), src.Value(2,2), src.Value(2,3), src.Value(2,4),
        src.Value(3,1), src.Value(3,2), src.Value(3,3), src.Value(3,4)
    )
    return new_trsf

def invert_trsf(src: gp_Trsf) -> gp_Trsf:
    """Invert a gp_Trsf matrix."""
    new_t = clone_trsf(src)
    new_t.Invert()
    return new_t

def _convert_location(trsf: gp_Trsf):
    """Convert gp_Trsf to [translation, axis, angle]."""
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

def save_shape_to_step(shape: TopoDS_Shape, filename: Path):
    """Save a TopoDS_Shape to a STEP file."""
    pc_logging.debug(f"Saving shape to {filename}")
    writer = STEPControl_Writer()
    status = writer.Transfer(shape, STEPControl_AsIs)
    if status != 1:
        raise ValueError(f"Transfer error for {filename}")
    status = writer.Write(str(filename))
    if status != 1:
        raise ValueError(f"Write error for {filename}")

def import_part(project: Project, shape: TopoDS_Shape, part_name: str, parent_folder: Path, config: dict) -> str:
    """Save shape as STEP, add part to project, return path without extension."""
    step_file = parent_folder / f"{part_name}.step"
    pc_logging.debug(f"Importing part '{part_name}' => {step_file}")
    save_shape_to_step(shape, step_file)
    import_part_action(
        project,
        "step",
        part_name,
        str(step_file),
        config,
        target_dir=str(parent_folder)
    )
    return str(step_file.with_suffix(""))

def shape_signature(shape: TopoDS_Shape) -> tuple:
    """Compute a bounding box + volume signature for dedup."""
    bnd = Bnd_Box()
    BRepBndLib.Add_s(shape, bnd)
    xmin, ymin, zmin, xmax, ymax, zmax = bnd.Get()

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    vol = props.Mass()

    def r(x):
        return round(x, 5)
    return (
        r(xmin), r(ymin), r(zmin),
        r(xmax), r(ymax), r(zmax),
        r(vol)
    )

def parse_label_recursive(label, shape_tool, parent_trsf: gp_Trsf, visited):
    """
    Recursively parse a label. If it's an assembly, explore children.
    If it's a simple shape, return a part node.
    Otherwise, fallback for compounds with multiple SOLIDs.
    """
    if label in visited:
        return None
    visited.add(label)

    loc = shape_tool.GetLocation_s(label)
    local_trsf = loc.Transformation()
    combined_trsf = gp_Trsf()
    combined_trsf.Multiply(parent_trsf)
    combined_trsf.Multiply(local_trsf)

    name = get_label_name(label, default="Unnamed")

    # Check if assembly
    if shape_tool.IsAssembly_s(label):
        pc_logging.debug(f" Assembly label: {name}")
        node = {
            "type": "assembly",
            "name": name,
            "trsf": combined_trsf,
            "children": []
        }
        child_seq = TDF_LabelSequence()
        shape_tool.GetComponents_s(label, child_seq)
        for i in range(child_seq.Length()):
            child_lbl = child_seq.Value(i + 1)
            sub_node = parse_label_recursive(child_lbl, shape_tool, combined_trsf, visited)
            if sub_node:
                node["children"].append(sub_node)
        return node

    # Check if simple shape
    if shape_tool.IsSimpleShape_s(label):
        shape = shape_tool.GetShape_s(label)
        if not shape.IsNull():
            pc_logging.debug(f"Simple part label: {name}")
            return {
                "type": "part",
                "name": name,
                "shape": shape,
                "trsf": combined_trsf
            }

    # Fallback: possibly a compound with multiple SOLIDs
    shape = shape_tool.GetShape_s(label)
    if not shape.IsNull():
        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        solids = []
        while explorer.More():
            solids.append(explorer.Current())
            explorer.Next()

        if len(solids) > 1:
            pc_logging.debug(f"Compound with {len(solids)} SOLIDs: {name}")
            children_nodes = []
            idx = 1
            for s in solids:
                local_t = clone_trsf(s.Location().Transformation())
                solid_trsf = gp_Trsf()
                solid_trsf.Multiply(combined_trsf)
                solid_trsf.Multiply(local_t)

                part_node = {
                    "type": "part",
                    "name": f"{name}_solid{idx}",
                    "shape": s,
                    "trsf": solid_trsf
                }
                children_nodes.append(part_node)
                idx += 1

            return {
                "type": "assembly",
                "name": name,
                "trsf": combined_trsf,
                "children": children_nodes
            }
        else:
            pc_logging.debug(f"Single solid fallback: {name}")
            return {
                "type": "part",
                "name": name,
                "shape": shape,
                "trsf": combined_trsf
            }
    return None

def read_step_as_tree(step_file: str):
    """Read a STEP file via XDE and build a recursive node tree."""
    if not os.path.isfile(step_file):
        raise FileNotFoundError(step_file)

    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("XDE-doc"))
    app.NewDocument(TCollection_ExtendedString("XmlXCAF"), doc)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    reader = STEPCAFControl_Reader()
    status = reader.ReadFile(step_file)
    if status != IFSelect_RetDone:
        raise ValueError(f"Cannot read STEP: {step_file}")
    reader.Transfer(doc)

    free_labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_labels)

    visited = set()
    roots = []
    identity = gp_Trsf()

    for i in range(free_labels.Length()):
        lbl = free_labels.Value(i + 1)
        node = parse_label_recursive(lbl, shape_tool, identity, visited)
        if node:
            roots.append(node)

    pc_logging.info(f"Found {len(roots)} top-level nodes.")
    return roots

def flatten_assembly_tree(node, parent_folder: Path, project: Project, config: dict):
    """
    Flatten a recursive node tree into a single assembly structure.
    Deduplicate shapes and save parts.
    """
    node_type = node["type"]
    node_name = node["name"]
    global_trsf = node["trsf"]

    if node_type == "assembly":
        child_links = []
        for ch in node.get("children", []):
            child_links.append(flatten_assembly_tree(ch, parent_folder, project, config))
        return {
            "type": "assembly",
            "name": node_name,
            "links": child_links,
            "location": [[0, 0, 0], [1, 0, 0], 0]
        }
    else:
        shape = node["shape"]
        # Zero the geometry for dedup
        inv_trsf = invert_trsf(global_trsf)
        zeroed_shape = BRepBuilderAPI_Transform(shape, inv_trsf, True).Shape()

        sig = shape_signature(zeroed_shape)
        if sig in g_shape_map:
            reused_part_name, reused_part_path = g_shape_map[sig]
            pc_logging.debug(f"Reusing part '{reused_part_name}' for '{node_name}'")
            return {
                "type": "part",
                "name": node_name,
                "part": reused_part_path,
                "location": _convert_location(global_trsf)
            }
        else:
            pc_logging.debug(f"New unique shape => {node_name}")
            part_path_noext = import_part(project, zeroed_shape, node_name, parent_folder, config)
            g_shape_map[sig] = (node_name, part_path_noext)
            return {
                "type": "part",
                "name": node_name,
                "part": part_path_noext,
                "location": _convert_location(global_trsf)
            }

def import_assy_action(
    project: Project,
    file_type: str,
    assembly_file: str,
    config: dict
):
    """
    Main function to import a STEP assembly:
    1) Build a node tree from XDE.
    2) Flatten to a single .assy with dedup.
    3) Add assembly to project.
    """
    g_shape_map.clear()

    pc_logging.info(f"[INFO] Importing assembly from STEP file: {assembly_file}")
    roots = read_step_as_tree(assembly_file)
    if not roots:
        raise ValueError(f"No shapes found in {assembly_file}")

    name = Path(assembly_file).stem
    out_folder = Path(assembly_file).parent / name
    out_folder.mkdir(parents=True, exist_ok=True)

    # If multiple root nodes, create a top-level assembly
    if len(roots) > 1:
        from OCP.gp import gp_Trsf
        pc_logging.debug(f"Creating a top-level assembly for {len(roots)} root nodes")
        top_node = {
            "type": "assembly",
            "name": f"{name}_top",
            "trsf": gp_Trsf(),
            "children": roots
        }
        final_tree = top_node
    else:
        final_tree = roots[0]

    top_data = flatten_assembly_tree(final_tree, out_folder, project, config)
    assy_name = top_data["name"]
    assy_file = out_folder / f"{assy_name}.assy"

    if top_data["type"] == "assembly":
        data = {
            "name": top_data["name"],
            "description": config.get("desc", ""),
            "links": top_data.get("links", [])
        }
    else:
        data = {
            "name": top_data["name"],
            "description": config.get("desc", ""),
            "links": []
        }

    with open(assy_file, "w") as f:
        yaml.dump(data, f, default_flow_style=False)

    project.add_assembly("assy", str(assy_file), config)
    pc_logging.info(f"Created single .assy => {assy_file}")
    return data["name"]
