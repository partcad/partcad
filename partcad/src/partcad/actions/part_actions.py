import os
import shutil
from pathlib import Path
import tempfile
from typing import Optional
import partcad
from partcad.context import Context
import partcad.logging as pc_logging
from partcad.project import Project
from partcad.utils import resolve_resource_path
from partcad.adhoc.convert import convert_cad_file

# Mapping of target formats to file extensions.
EXTENSION_MAPPING = {
    "step": "step",
    "brep": "brep",
    "stl": "stl",
    "3mf": "3mf",
    "threejs": "json",
    "obj": "obj",
    "gltf": "gltf",
}


def add_part_action(project: Project, kind: str, path: str, config: Optional[dict] = None):
    """Add an existing part to the project without copying."""
    config = config or {}
    path = Path(path)
    name = path.stem

    pc_logging.info(f"Adding part '{name}' ({kind}) from '{path}'")

    with pc_logging.Process("AddPart", project.name):
        result = project.add_part(kind, str(path), config)
        if result:
            pc_logging.info(f"Part '{name}' added successfully.")


def import_part_action(
    project: Project,
    kind: str,
    name: str,
    source_path: str,
    config: Optional[dict] = None,
    target_format: Optional[str] = None,
    target_dir: Optional[str] = None
):
    """
    Import an existing part into the project by copying it to the target folder and updating the configuration.
    Optionally perform an ad-hoc conversion if target_format is specified and differs from the source kind.

    Args:
        project (Project): The active PartCAD project.
        kind (str): The original part type (e.g., "step").
        name (str): The part name.
        source_path (str): Path to the source file.
        config (dict, optional): Additional configuration.
        target_format (str, optional): Format for conversion before saving.
        target_dir (str, optional): Directory inside the project to store the imported part.
    """
    config = config or {}
    source_path = Path(source_path).resolve()
    original_source = source_path

    pc_logging.info(f"Importing '{name}' ({kind}) from '{source_path}'")

    if not source_path.exists():
        raise ValueError(f"Source file '{source_path}' not found.")

    # If conversion is needed (target_format provided and differs from kind)
    temp_dir = None
    if target_format and target_format != kind:
        temp_dir = Path(tempfile.mkdtemp())
        converted_path = temp_dir / f"{name}.{target_format}"
        pc_logging.info(f"Performing ad-hoc conversion: {kind} -> {target_format}")
        convert_cad_file(str(source_path), kind, str(converted_path), target_format)
        if not converted_path.exists():
            raise RuntimeError(f"Ad-hoc conversion failed: {source_path} -> {converted_path}")
        # Update kind and source_path after conversion
        kind = target_format
        source_path = converted_path
        pc_logging.info(f"Ad-hoc conversion successful: {converted_path}")

    # Determine target folder inside project
    target_folder = (Path(project.path) / target_dir).resolve() if target_dir else Path(project.path).resolve()
    target_folder.mkdir(parents=True, exist_ok=True)
    target_path = (target_folder / f"{name}.{kind}").resolve()

    # Log the target path and copy if needed
    if target_path.exists() and source_path.samefile(target_path):
        pc_logging.warning(f"Skipping copy: source and target are the same ({source_path}).")
    else:
        try:
            shutil.copy2(source_path, target_path)
        except shutil.Error as e:
            raise ValueError(f"Failed to copy '{source_path}' -> '{target_path}': {e}")

    # Update project configuration and add the part
    add_part_action(project, kind, str(target_path), config)
    pc_logging.info(f"Part '{name}' imported successfully.")

    # Optionally, reload the context to refresh project parts
    ctx = Context(project.ctx.root_path)
    project = ctx.get_project(partcad.ROOT)

    # Cleanup temporary conversion directory if conversion was performed
    if temp_dir:
        try:
            shutil.rmtree(temp_dir)
            pc_logging.info(f"Cleaned up temporary conversion directory: {temp_dir}")
        except Exception as e:
            pc_logging.warning(f"Failed to remove temp directory '{temp_dir}': {e}")


def convert_part_action(project: Project, object_name: str, target_format: str,
                        output_dir: Optional[str] = None, dry_run: bool = False):
    """Convert a part to a new format and update its configuration."""
    # Resolve the package and part name based on the project's context.
    package_name, part_name = resolve_resource_path(project.name, object_name)
    pc_logging.info(f"Resolving package '{package_name}', part '{part_name}'")

    if project.name != package_name:
        project = project.ctx.get_project(package_name)

    if project is None:
        raise ValueError(f"Project '{package_name}' not found for '{part_name}'")

    pc_logging.info(f"Using project '{project.name}', located at '{project.path}'")

    part_config = project.get_part_config(part_name)
    if part_config is None:
        raise ValueError(f"Object '{part_name}' not found in project configuration.")

    # Determine the current part path.
    part_path = part_config.get("path")
    old_path = (Path(project.path) / part_path) if part_path else Path(project.config_dir) / f"{part_name}.{target_format}"

    new_extension = EXTENSION_MAPPING.get(target_format, target_format)
    full_output_dir = Path(output_dir).resolve() if output_dir else old_path.parent.resolve()
    new_path = full_output_dir / f"{old_path.stem}.{new_extension}"

    pc_logging.info(f"Converting '{part_name}' ({old_path.suffix[1:]} -> {new_extension}) -> {new_path}")

    full_output_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        pc_logging.info(f"[Dry Run] No changes made for '{part_name}'.")
        return

    with pc_logging.Process("Convert", part_name):
        project.convert(
            sketches=[], interfaces=[], parts=[part_name], assemblies=[],
            target_format=target_format, output_dir=str(new_path)
        )

    pc_logging.info(f"Conversion of '{part_name}' completed.")

    try:
        # Get the new part path relative to the project.
        config_path = new_path.relative_to(project.path)
    except ValueError:
        config_path = new_path

    new_config = {"type": target_format, "path": str(config_path)}
    project.update_part_config(part_name, new_config)

    pc_logging.info(f"Updated configuration for '{part_name}': {config_path}")
