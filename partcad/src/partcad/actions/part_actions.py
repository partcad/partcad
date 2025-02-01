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


def deep_copy_metadata(source_path, target_path):
    """
    Copies file attributes and metadata from the source to the target file.

    :param source_path: Path to the source file.
    :param target_path: Path to the copied file.
    """
    # Preserve timestamps and file permissions
    shutil.copystat(source_path, target_path)

    # If there's an associated metadata/config file, copy it too
    meta_file = source_path.with_suffix(source_path.suffix + ".json")
    target_meta_file = target_path.with_suffix(target_path.suffix + ".json")

    if meta_file.exists():
        shutil.copy(meta_file, target_meta_file)
        logging.info(f"Copied metadata file: {meta_file} -> {target_meta_file}")

    logging.info(f"Preserved file attributes for {target_path}")

def import_part_action(project, kind, name, source_path, config=None, target_format=None):
    """
    Import a part into the project by copying it, preserving metadata, and optionally converting it.

    :param project: Project object
    :param kind: Type of the part (e.g., stl, step, brep)
    :param name: Name of the part
    :param source_path: Path to the source file
    :param config: Additional configuration for the part
    :param target_format: (Optional) Target format to convert the part
    """
    config = config or {}
    source_path = Path(source_path)
    target_path = Path(project.path) / f"{name}.{kind}"

    logging.info(f"Importing part {name} from {source_path} to {target_path}")

    if not source_path.exists():
        raise ValueError(f"Source file '{source_path}' does not exist.")

    # Copy file and metadata
    shutil.copy(source_path, target_path)
    deep_copy_metadata(source_path, target_path)

    # Add part to project
    project.add_part(kind, str(target_path), config)
    project.update_part_config(name, {"path": str(target_path)})

    logging.info(f"Part {name} imported successfully with metadata.")

    # Convert if needed
    if target_format and target_format != kind:
        logging.info(f"Converting {name} from {kind} to {target_format}...")
        convert_part_action(project, name, target_format, in_place=True)


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
