import shutil
from pathlib import Path
import partcad.logging as logging

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


def convert_part_action(project, part_name, target_format):
    """
    Convert a part to a new format.

    :param project: Project object
    :param part_name: Name of the part
    :param target_format: Target format for conversion
    """
    logging.info(f"Converting part {part_name} to format {target_format}")
    ext_by_format = {"threejs": "json", "stl": "stl", "step": "step", "brep": "brep"}  # Mapping for extensions
    target_extension = ext_by_format.get(target_format, target_format)  # Get the correct extension
    converted_path = f"{part_name}.{target_extension}"  # Define the new file path

    # Perform the conversion
    project.convert(parts=[part_name], target_format=target_format, in_place=True)

    # Update the part's configuration with the new format and path
    project.update_part_config(part_name, {"path": converted_path, "type": target_format})
    logging.info(f"Part {part_name} converted to {target_format} successfully.")
