from pathlib import Path
import shutil
import tempfile
from typing import Optional
import partcad
from partcad.context import Context
import partcad.logging as pc_logging
from partcad.project import Project
from partcad.utils import resolve_resource_path
from partcad.adhoc.convert import convert_cad_file

EXTENSION_MAPPING = {
    "step": "step",
    "brep": "brep",
    "stl": "stl",
    "3mf": "3mf",
    "threejs": "json",
    "obj": "obj",
    "gltf": "gltf",
    "cadquery": "py",
    "build123d": "py",
    "scad": "scad",
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


def import_part_action(project: Project, kind: str, name: str, source_path: str,
                       config: Optional[dict] = None, target_format: Optional[str] = None):
    """Import an existing part into the project, optionally converting it first using ad-hoc conversion."""
    config = config or {}
    source_path = Path(source_path).resolve()
    original_source = source_path

    pc_logging.info(f"Importing '{name}' ({kind}) from '{source_path}'")

    if not source_path.exists():
        raise ValueError(f"Source file '{source_path}' not found.")

    # If a target format is specified, perform ad-hoc conversion before adding to project
    if target_format and target_format != kind:
        temp_dir = Path(tempfile.mkdtemp())
        converted_path = temp_dir / f"{name}.{target_format}"

        pc_logging.info(f"Performing ad-hoc conversion: {kind} -> {target_format}")
        convert_cad_file(str(source_path), kind, str(converted_path), target_format)

        if not converted_path.exists():
            raise RuntimeError(f"Ad-hoc conversion failed: {source_path} -> {converted_path}")

        # Update the kind and source path for further processing
        kind = target_format
        source_path = converted_path
        pc_logging.info(f"Ad-hoc conversion successful: {converted_path}")

    # Define target path inside the project
    target_path = (Path(project.path) / f"{name}.{kind}").resolve()

    if target_path.exists() and source_path.samefile(target_path):
        pc_logging.warning(f"Skipping copy: source and target paths are the same ({source_path}).")
    else:
        try:
            shutil.copy2(source_path, target_path)
        except shutil.Error as e:
            raise ValueError(f"Failed to copy '{source_path}' -> '{target_path}': {e}")

    add_part_action(project, kind, str(target_path), config)
    pc_logging.info(f"Part '{name}' imported successfully.")

    # Reload context to refresh project parts
    ctx = Context(project.ctx.root_path)
    project = ctx.get_project(partcad.ROOT)

    # Cleanup temporary converted file if ad-hoc conversion was performed
    if source_path != original_source:
        try:
            shutil.rmtree(temp_dir)
            pc_logging.info(f"Cleaned up temporary conversion directory: {temp_dir}")
        except Exception as e:
            pc_logging.warning(f"Failed to remove temp directory '{temp_dir}': {e}")


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge two dictionaries; override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def convert_part_action(project: Project, object_name: str, target_format: Optional[str] = None,
                        output_dir: Optional[str] = None, dry_run: bool = False):
    """
    Convert a part to a new format and update its configuration.

    For enrich/alias/AI parts, the original configuration is
    merged with the enrich modifications. The file is looked up from the source project and base part.

    If target_format is not provided, conversion uses the original type.
    If provided and different, a secondary conversion is applied.
    """
    # Resolve package and part name.
    package_name, part_name = resolve_resource_path(project.name, object_name)
    pc_logging.debug(f"Resolving package '{package_name}', part '{part_name}'")
    if project.name != package_name:
        project = project.ctx.get_project(package_name)
    if not project:
        raise ValueError(f"Project '{package_name}' not found for '{part_name}'")
    pc_logging.debug(f"Using project '{project.name}', located at '{project.path}'")

    # Load current part configuration.
    part_config = project.get_part_config(part_name)
    part_type = part_config["type"]

    if part_config is None:
        raise ValueError(f"Object '{part_name}' not found in project configuration.")

    # If "source" exists, merge base config and use the base part's name for file lookup.
    if "source" in part_config:
        base_package, base_part_name = resolve_resource_path(project.name, part_config["source"])
        base_project = project.ctx.get_project(base_package)
        if not base_project:
            raise ValueError(f"Base project '{base_package}' not found for part '{part_name}'.")

        base_part_config = base_project.get_part_config(base_part_name)
        if not base_part_config:
            raise ValueError(f"Base part '{base_part_name}' not found in project '{base_project.name}'.")
        original_type = base_part_config.get("type")
        merged_config = deep_merge(base_part_config, part_config)
        merged_config["type"] = original_type  # Reset to original type.
        merged_config.pop("source", None)

        # Use base part's file path if not provided.
        if "path" not in merged_config and "path" in base_part_config:
            merged_config["path"] = base_part_config["path"]

        new_config = merged_config
        source_project_for_file = base_project
        file_source_name = base_part_name
    else:
        original_type = part_config.get("type")
        new_config = part_config.copy()
        source_project_for_file = project
        file_source_name = part_name

    # Remove unnecessary keys
    for key in ["name", "orig_name", "manufacturable", "with"]:
        new_config.pop(key, None)

    # Determine conversion target type.
    conversion_target = original_type if not target_format else original_type

    # Determine source file location.
    if new_config.get("path"):
        old_path = (Path(source_project_for_file.path) / new_config["path"]).resolve()
    else:
        old_path = Path(source_project_for_file.config_dir) / f"{file_source_name}.{EXTENSION_MAPPING.get(original_type)}"

    new_ext = EXTENSION_MAPPING.get(conversion_target, conversion_target)
    full_output_dir = Path(output_dir).resolve() if output_dir else Path(project.path).resolve()
    new_file_name = f"{part_name}.{new_ext}"

    if part_type != conversion_target:
        pc_logging.info(f"Converting '{part_name}' from '{part_type}' to '{conversion_target}'.")
    full_output_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        pc_logging.info(f"[Dry Run] No changes made for '{part_name}'.")
        return

    source_path = old_path

    # Copy the file into the target package.
    target_path = (Path(project.path) / new_file_name).resolve()
    if not ((target_path.exists() and source_path.samefile(target_path)) or part_type == conversion_target):
        try:
            shutil.copy2(source_path, target_path)
        except shutil.Error as e:
            raise ValueError(f"Failed to copy '{source_path}' → '{target_path}': {e}")

    try:
        config_path = target_path.relative_to(Path(project.path))
    except ValueError:
        config_path = target_path

    # Update configuration
    updated_config = deep_merge(new_config, {"type": conversion_target, "path": str(config_path)})
    project.set_part_config(part_name, updated_config)
    pc_logging.debug(f"Updated configuration for '{part_name}': {config_path}")

    # Secondary conversion if needed
    if target_format and target_format != conversion_target:
        final_ext = EXTENSION_MAPPING.get(target_format, target_format)
        final_new_path = Path(f"{str(old_path).split('.')[0]}.{final_ext}")
        pc_logging.info(f"Converting: {conversion_target} to {target_format}.")
        project.convert(
            sketches=[], interfaces=[], parts=[part_name], assemblies=[],
            target_format=target_format, output_dir=str(final_new_path)
        )
        try:
            final_config_path = final_new_path.relative_to(Path(project.path))
        except ValueError:
            final_config_path = final_new_path
        project.update_part_config(part_name, {"type": target_format, "path": str(final_config_path)})
        pc_logging.debug(f"Final updated configuration for '{part_name}': {final_config_path}")
