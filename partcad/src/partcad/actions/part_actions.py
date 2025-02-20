from contextlib import suppress
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
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def get_base_part_config(project: Project, part_config: dict, part_name: str):
    """Retrieve the base part configuration if the part is an 'enrich' or 'alias'."""
    if "source" not in part_config and "source_resolved" not in part_config:
        return part_config, project, part_name

    source_key = "source_resolved" if "source_resolved" in part_config else "source"
    base_package, base_part_name = resolve_resource_path(project.name, part_config[source_key])
    base_project = project.ctx.get_project(base_package)
    if not base_project:
        raise ValueError(f"Base project '{base_package}' not found for part '{part_name}'.")

    base_part_config = base_project.get_part_config(base_part_name)
    if not base_part_config:
        raise ValueError(f"Base part '{base_part_name}' not found in project '{base_project.name}'.")

    merged_config = deep_merge(base_part_config, part_config)
    merged_config["type"] = base_part_config.get("type", part_config["type"])
    merged_config.pop(source_key, None)
    if "path" not in merged_config and "path" in base_part_config:
        merged_config["path"] = base_part_config["path"]

    return merged_config, base_project, base_part_name

def get_source_path(project: Project, config: dict, part_name: str):
    """Determine the source file location based on part configuration."""
    if "path" in config:
        return (Path(project.path) / config["path"]).resolve()
    part_type = config.get("type")
    return Path(project.config_dir) / f"{part_name}.{EXTENSION_MAPPING.get(part_type, part_type)}"

def perform_conversion(project: Project, part_name, original_type: str,
                       part_config: dict, source_path: Path, target_format: str, output_dir: Optional[str]):
    """Handles file conversion and updates project configuration."""
    new_ext = EXTENSION_MAPPING.get(target_format, target_format)
    if output_dir:
        output_path = Path(output_dir) / f"{source_path.stem}.{new_ext}"
    elif "path" in part_config:
        existing_path = Path(project.path) / part_config["path"]
        output_path = existing_path.with_suffix(f".{new_ext}")
    else:
        output_path = Path(project.path) / f"{part_name}.{new_ext}"

    if output_path.exists() and source_path.samefile(output_path):
        pc_logging.warning(f"Skipping conversion: source and target paths are identical ({source_path}).")
        return output_path

    pc_logging.info(f"Converting '{part_name}': {original_type} to {target_format} ({output_path})")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pc_logging.Process("Convert", part_name):
        if original_type in ["enrich", "alias"]:
            shutil.copy2(source_path, output_path)
        else:
            project.convert(
                sketches=[], interfaces=[], parts=[part_name], assemblies=[],
                target_format=target_format, output_dir=str(output_path)
            )

    return output_path

def convert_part_action(project: Project, object_name: str, target_format: Optional[str] = None,
                        output_dir: Optional[str] = None, dry_run: bool = False):
    """
    Convert a part to a new format and update its configuration.
    """
    package_name, part_name = resolve_resource_path(project.name, object_name)
    project = project.ctx.get_project(package_name) if project.name != package_name else project
    if not project:
        raise ValueError(f"Project '{package_name}' not found for '{part_name}'")

    part = project.get_part(part_name)
    if not part:
        raise ValueError(f"Part '{part_name}' not found in project '{project.name}'")

    part_config = part.config
    part_type = part_config.get("type")

    part_config, source_project, source_part_name = get_base_part_config(project, part_config, part_name)
    source_path = get_source_path(source_project, part_config, source_part_name)
    conversion_target = part_config.get("type")

    if dry_run:
        pc_logging.info(f"[Dry Run] No changes made for '{part_name}'.")
        return

    if part_type != conversion_target:
        converted_path = perform_conversion(project, part_name, part_type, part_config,
                                            source_path, conversion_target, output_dir)

    with suppress(ValueError):
        config_path = converted_path.relative_to(Path(project.path))

    updated_config = deep_merge(part_config, {"type": conversion_target, "path": str(config_path)})
    updated_config.pop("package", None)
    updated_config.pop("with", None)
    project.set_part_config(part_name, updated_config)
    pc_logging.debug(f"Updated configuration for '{part_name}': {config_path}")

    # Secondary conversion if needed
    if target_format and target_format != conversion_target:
        final_path = perform_conversion(project, part_name, conversion_target, updated_config,
                                        converted_path, target_format, output_dir)
        try:
            final_config_path = final_path.relative_to(Path(project.path))
        except ValueError:
            final_config_path = final_path
        project.update_part_config(part_name, {"type": target_format, "path": str(final_config_path)})
        pc_logging.debug(f"Final updated configuration for '{part_name}': {final_config_path}")
