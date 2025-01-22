import shutil
import copy
from pathlib import Path
import partcad as pc
from partcad.context import Context
import partcad.logging as pc_logging
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


import os
from pathlib import Path
import shutil
import partcad.logging as pc_logging
from partcad.utils import resolve_resource_path

def resolve_enrich_action(ctx, part_name):
    pc_logging.info(f"Resolving enrich part: {part_name}")

    # Resolve project and part
    project_name, item_name = resolve_resource_path(ctx.get_current_project_path(), part_name)
    project = ctx.get_project(project_name)
    if not project:
        raise RuntimeError(f"Failed to find a project for '{project_name}'.")

    pc_logging.info(f"Using project: {project.name} at {project.path}")

    part_config = project.get_part_config(item_name)
    if not part_config:
        raise ValueError(f"Part '{item_name}' not found in project '{project_name}'.")

    pc_logging.debug(f"Enrich part configuration: {part_config}")

    if part_config["type"] != "enrich":
        raise ValueError(f"Part '{item_name}' is not of type 'enrich'.")

    # Fetch source part configuration
    source_name = part_config["source"]
    source_part = ctx.get_part(source_name)
    source_config = source_part.config
    pc_logging.debug(f"Source part configuration: {source_config}")

    # Deep copy of source configuration
    resolved_config = copy.deepcopy(source_config)

    # Apply enrich-specific modifications
    if "with" in part_config:
        for key, value in part_config["with"].items():
            resolved_config.setdefault("parameters", {}).setdefault(key, {})
            resolved_config["parameters"][key].update({
                "type": type(value).__name__,
                "default": value,
            })

    # Add port locations if specified
    if "ports" in part_config:
        resolved_config.setdefault("ports", {}).update(part_config["ports"])

    # Determine target path
    target_path = Path(project.path) / f"{item_name}.{resolved_config['type']}"
    try:
        source_path = Path(source_part.path)
        shutil.copy(source_path, target_path)
        pc_logging.info(f"Files moved: {source_path} -> {target_path}")
    except Exception as e:
        raise RuntimeError(f"Failed to move files for '{item_name}': {e}")

    # Update the part configuration
    resolved_config["path"] = str(target_path)
    try:
        project.update_part_config(item_name, resolved_config)
        updated_config = project.get_part_config(item_name)
        pc_logging.info(f"Updated part configuration for '{item_name}': {updated_config}")
    except Exception as e:
        pc_logging.error(f"Failed to update part configuration for '{item_name}': {e}")
        # Manually add and save config
        project.parts[item_name] = resolved_config
        project.save_config()
        pc_logging.info(f"Manually added and saved part configuration for '{item_name}'.")

    pc_logging.info(f"Enrich part '{item_name}' resolved successfully.")
