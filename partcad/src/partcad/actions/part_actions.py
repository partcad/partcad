import copy
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


def convert_part_action(project: Project, object_name: str, target_format: str,
                        output_dir: Optional[str] = None, dry_run: bool = False):
    """Convert a part to a new format and update its configuration."""
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
        config_path = new_path.relative_to(project.path)
    except ValueError:
        config_path = new_path

    new_config = {"type": target_format, "path": str(config_path)}
    project.update_part_config(part_name, new_config)

    pc_logging.info(f"Updated configuration for '{part_name}': {config_path}")


def resolve_enrich_action(project: Project, part_name: str, dry_run: bool = False):
    """
    Resolve an enrich part to its original type and update its definition.

    :param project: Project object
    :param part_name: Name of the enrich part to resolve.
    :param dry_run: If True, simulates resolution without making actual changes.
    """

    package_name, part_name = resolve_resource_path(project.name, part_name)

    pc_logging.info(f"Resolving package '{package_name}', part '{part_name}'")

    if project.name != package_name:
        project = project.ctx.get_project(package_name)

    part_config = project.get_part_config(part_name)
    if not part_config or part_config["type"] != "enrich":
        raise ValueError(f"Invalid or missing enrich part '{part_name}' in project '{project.name}'.")

    source_name = part_config["source"]
    source_project_name, source_part_name = resolve_resource_path(project.name, source_name)

    if source_project_name.startswith(project.name):
        pc_logging.info("Source is a subdirectory of the same project, using current project.")
        source_project = project
    else:
        source_project = project.ctx.get_project(source_project_name)

    if not source_project:
        raise ValueError(f"Source project '{source_project_name}' not found for part '{source_part_name}'.")

    source_part = source_project.get_part(source_part_name)
    if not source_part or not source_part.path:
        raise ValueError(f"Source part '{source_part_name}' has no valid path in project '{source_project_name}'.")

    source_config = source_part.config
    resolved_config = copy.deepcopy(source_config)

    for key, value in part_config.get("with", {}).items():
        resolved_config.setdefault("parameters", {}).setdefault(key, {})
        resolved_config["parameters"][key].update({
            "type": type(value).__name__,
            "default": value,
        })
    resolved_config.setdefault("ports", {}).update(part_config.get("ports", {}))

    file_extension = EXTENSION_MAPPING.get(resolved_config["type"], resolved_config["type"])
    target_path = Path(project.path) / f"{part_name}.{file_extension}"

    if dry_run:
        pc_logging.info(f"[Dry Run] Would resolve enrich part '{part_name}' and save it to '{target_path}'.")
        return

    shutil.copy(Path(source_part.path), target_path)
    pc_logging.info(f"Copied source part from {source_part.path} to {target_path}")

    resolved_config["path"] = str(target_path)
    project.update_part_config(part_name, resolved_config)
    pc_logging.info(f"Resolved part '{part_name}' updated in project configuration.")
