import shutil
from pathlib import Path
import partcad.logging as logging
import os

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

    logging.info(f"Adding the part {name} of type {kind} from {path}")

    # Add the part to the project
    if project.add_part(kind, str(path), config):
        project.update_part_config(name, {"path": str(path)})
        path.touch()
        logging.info(f"Part {name} added successfully.")


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

    logging.info(f"Importing the part {name} of type {kind} from {source_path} to {target_path}")

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
    logging.info(f"Part {name} imported and added successfully.")


def convert_part_action(project, object_name, target_format, output_dir=None, in_place=False, dry_run=False):
    """
    Convert an object (part, assembly, or scene) to a new format.

    :param project: Project object
    :param object_name: Name of the object to convert
    :param target_format: Target format for conversion
    :param output_dir: Optional output directory for the converted file
    :param in_place: If True, update the object's type in the configuration
    :param dry_run: If True, simulate conversion without modifying files
    """
    logging.info(f"Processing '{object_name}' in project '{project.name}'")

    part_config = project.get_part_config(object_name)
    old_path = part_config.get("path")

    base_file_name = os.path.splitext(os.path.basename(old_path))[0] if old_path else object_name
    new_file_name = f"{base_file_name}.{target_format}"

    # Determine full output directory
    full_output_dir = output_dir or (os.path.dirname(old_path) if old_path and not os.path.isabs(old_path) else project.path)
    new_path = os.path.join(full_output_dir, new_file_name)

    if dry_run:
        logging.info(f"Dry run: would convert '{old_path}' to '{new_path}', in_place={in_place}.")
        return

    # Perform conversion
    with logging.Process("Convert", object_name):
        project.convert(
            sketches=[], interfaces=[], parts=[object_name], assemblies=[],
            target_format=target_format, output_dir=new_path, in_place=in_place
        )

    # Update configuration if needed
    if in_place or output_dir:
        project.update_part_config(object_name, {"path": new_path, "type": target_format})

    logging.info(f"Conversion completed: {object_name} -> {new_path}")
