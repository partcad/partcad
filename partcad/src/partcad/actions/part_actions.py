import shutil
import copy
from pathlib import Path
import partcad.logging as pc_logging
from partcad.project import Project
from partcad.utils import resolve_resource_path

def add_part_action(project, kind, path, config=None):
    """
    Add a part to the project without copying.

    :param project: Project object
    :param kind: Type of the part (e.g., stl, step, brep)
    :param path: Path to the source file
    :param config: Additional configuration for the part
    """
    config = config or {}
    path = Path(path)  # Ensure path is a Path object
    name = path.stem  # Extract file name without extension

    pc_logging.info(f"Adding the part {name} of type {kind} from {path}")

    # Add the part to the project
    if project.add_part(kind, str(path), config):
        project.update_part_config(name, {"path": str(path)})
        path.touch()
        pc_logging.info(f"Part {name} added successfully.")


def import_part_action(project, kind, name, source_path, config=None):
    """
    Import a part into the project by copying it and adding.

    :param project: Project object
    :param kind: Type of the part (e.g., stl, step, brep)
    :param name: Name of the part
    :param source_path: Path to the source file
    :param config: Additional configuration for the part
    """
    config = config or {}
    source_path = Path(source_path)  # Ensure source_path is a Path object
    target_path = Path(project.path) / f"{name}.{kind}"  # Define the target file path

    pc_logging.info(f"Importing the part {name} of type {kind} from {source_path} to {target_path}")

    # Check if the source file exists
    if not source_path.exists():
        raise ValueError(f"Source file '{source_path}' does not exist.")

    # Copy the file to the project directory
    try:
        shutil.copy(source_path, target_path)
    except Exception as e:
        raise ValueError(f"Failed to copy file from {source_path} to {target_path}: {e}")

    # Add the part to the project
    project.add_part(kind, str(target_path), config)
    project.update_part_config(name, {"path": str(target_path)})
    pc_logging.info(f"Part {name} imported and added successfully.")


def convert_part_action(project, part_name, target_format):
    """
    Convert a part to a new format.

    :param project: Project object
    :param part_name: Name of the part
    :param target_format: Target format for conversion
    """
    pc_logging.info(f"Converting part {part_name} to format {target_format}")
    ext_by_format = {"threejs": "json", "stl": "stl", "step": "step", "brep": "brep"}  # Mapping for extensions
    target_extension = ext_by_format.get(target_format, target_format)  # Get the correct extension
    converted_path = f"{part_name}.{target_extension}"  # Define the new file path

    # Perform the conversion
    project.convert(parts=[part_name], target_format=target_format, in_place=True)

    # Update the part's configuration with the new format and path
    project.update_part_config(part_name, {"path": converted_path, "type": target_format})
    pc_logging.info(f"Part {part_name} converted to {target_format} successfully.")


EXTENSION_MAPPING = {
    "threejs": "json",
    "cadquery": "py",
    "build123d": "py",
    "scad": "scad",
    "step": "step",
    "brep": "brep",
    "stl": "stl",
    "3mf": "3mf",
    "obj": "obj",
    "gltf": "gltf",
}

def resolve_enrich_action(project: Project, part_name: str):
    """
    Resolve an enrich part to its original type and update its definition.

    :param project: Project object
    :param part_name: Name of the enrich part to resolve.
    """
    _, item_name = resolve_resource_path(project.name, part_name)

    part_config = project.get_part_config(item_name)
    if not part_config or part_config["type"] != "enrich":
        raise ValueError(f"Invalid or missing enrich part '{item_name}' in project '{project.name}'.")

    source_name = part_config["source"]
    source_project_name, source_item_name = resolve_resource_path(project.name, source_name)

    # Retrieve source project and part
    source_project = project.ctx.get_project(source_project_name)
    if not source_project:
        raise ValueError(f"Source project '{source_project_name}' not found for part '{source_item_name}'.")
    source_part = source_project.get_part(source_item_name)
    if not source_part or not source_part.path:
        raise ValueError(f"Source part '{source_item_name}' has no valid path in project '{source_project_name}'.")

    # Prepare resolved configuration
    source_config = source_part.config
    resolved_config = copy.deepcopy(source_config)

    # Apply modifications from the enrich configuration
    for key, value in part_config.get("with", {}).items():
        resolved_config.setdefault("parameters", {}).setdefault(key, {})
        resolved_config["parameters"][key].update({
            "type": type(value).__name__,
            "default": value,
        })
    resolved_config.setdefault("ports", {}).update(part_config.get("ports", {}))

    # Copy the source file and update path
    file_extension = EXTENSION_MAPPING.get(resolved_config["type"], resolved_config["type"])
    target_path = Path(project.path) / f"{item_name}.{file_extension}"
    shutil.copy(Path(source_part.path), target_path)
    pc_logging.info(f"Copied source part from {source_part.path} to {target_path}")

    # Update project configuration
    resolved_config["path"] = str(target_path)
    project.update_part_config(item_name, resolved_config)
    pc_logging.info(f"Resolved part '{item_name}' updated in project configuration.")
