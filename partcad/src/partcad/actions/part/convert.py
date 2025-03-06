from pathlib import Path
import shutil
from typing import Optional
import partcad.logging as pc_logging
from partcad.project import Project
from partcad.utils import resolve_resource_path


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

SHALLOW_COPY_SUFFICIENT_TYPES = ["alias", "enrich"]


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge two dictionaries; override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get_source_path(project: Project, config: dict, part_name: str) -> Path:
    """Get the physical path of the final base part file."""
    if "path" in config:
        source_path = (Path(project.path) / config["path"]).resolve()
    else:
        part_type = config.get("type")
        ext = EXTENSION_MAPPING.get(part_type, part_type)
        source_path = Path(project.config_dir) / f"{part_name}.{ext}"

    pc_logging.debug(f"Checking source path for '{part_name}': {source_path}")

    if not source_path.exists():
        raise FileNotFoundError(f"Source file '{source_path}' does not exist for conversion.")

    return source_path


def get_final_base_part_config(project: Project, part_config: dict, part_name: str):
    """Recursively resolve 'alias' and 'enrich' to find the original base part."""
    visited_sources = set()
    final_params = {}

    while part_config.get("type") in SHALLOW_COPY_SUFFICIENT_TYPES:
        source_key = "source_resolved" if "source_resolved" in part_config else "source"

        if source_key not in part_config:
            pc_logging.debug(f"Reached base part: '{part_name}', stopping resolution.")
            break

        source_value = part_config[source_key]

        if source_value in visited_sources:
            raise ValueError(f"Circular reference detected in part '{part_name}' (source: '{source_value}')")

        visited_sources.add(source_value)

        if "with" in part_config:
            final_params.update(part_config["with"])

        base_package, base_part_name = resolve_resource_path(project.name, source_value)
        base_project = project.ctx.get_project(base_package)

        if not base_project:
            raise ValueError(f"Base project '{base_package}' not found for part '{part_name}'.")

        base_part_config = base_project.get_part_config(base_part_name)

        if not base_part_config:
            raise ValueError(f"Base part '{base_part_name}' not found in project '{base_project.name}'.")

        pc_logging.debug(f"Resolving '{part_name}' → '{base_part_name}' (source: '{source_value}')")

        part_config = base_part_config
        project = base_project
        part_name = base_part_name

    if final_params:
        part_config.setdefault("with", {}).update(final_params)

    return part_config, project, part_name


def update_parameters_with_defaults(part_config: dict) -> dict:
    """Update parameters' default values using 'with' overrides, only for original parts."""
    if part_config.get("type") in SHALLOW_COPY_SUFFICIENT_TYPES:
        return part_config  # No need to update parameters for alias or enrich parts

    if "with" not in part_config or "parameters" not in part_config:
        return part_config

    parameters = part_config["parameters"]
    with_values = part_config["with"]

    for param_name, new_value in with_values.items():
        if param_name in parameters:
            param_data = parameters[param_name]

            if param_data["type"] == "int":
                new_value = int(new_value)
            elif param_data["type"] == "float":
                new_value = float(new_value)

            param_data["default"] = new_value

            if "min" in param_data and param_data["min"] == new_value:
                del param_data["min"]
            if "max" in param_data and param_data["max"] == new_value:
                del param_data["max"]

    return part_config


def perform_conversion(project: Project, part_name: str, original_type: str,
                       part_config: dict, source_path: Path, target_format: str,
                       output_dir: Optional[str], dependencies_list: list = []) -> Path:
    """Handles file conversion and updates project configuration."""
    new_ext = EXTENSION_MAPPING.get(target_format, target_format)
    if output_dir:
        output_path = Path(output_dir) / f"{part_name}.{new_ext}"
    elif "path" in part_config:
        existing_path = Path(project.path) / part_config["path"]
        output_path = existing_path.with_name(f"{part_name}.{new_ext}")
    else:
        output_path = Path(project.path) / f"{part_name}.{new_ext}"

    if output_path.exists() and source_path.samefile(output_path):
        pc_logging.warning(f"Skipping conversion: source and target paths are identical ({source_path}).")
        return output_path

    pc_logging.info(f"Converting '{part_name}': {original_type} to {target_format} ({output_path})")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pc_logging.Process("Convert", part_name):
        if original_type in SHALLOW_COPY_SUFFICIENT_TYPES:
            shutil.copy2(source_path, output_path)
            dependencies_list += copy_dependencies(project, part_config, output_dir)
        else:
            project.convert(
                sketches=[], interfaces=[], parts=[part_name], assemblies=[],
                target_format=target_format, output_dir=str(output_path)
            )

    if not output_path.exists():
        raise RuntimeError(f"Conversion failed: output file '{output_path}' was not created.")

    return output_path


def copy_dependencies(source_project: Project, part_config: dict, output_dir: Optional[str]):
    """Copy dependencies (additional files) associated with a part."""
    dependencies = part_config.get("dependencies", [])
    copied_files = []

    if not dependencies:
        return copied_files  # Ensure dependencies are present in config even if not copied

    if output_dir:
        output_dir = output_dir.resolve()

    for dep in dependencies:
        dep_source_path = (Path(source_project.path) / dep).resolve()
        dep_target_path = (output_dir / Path(dep).name).resolve() if output_dir else dep_source_path

        if not dep_source_path.exists():
            pc_logging.warning(f"Dependency '{dep}' not found in project '{source_project.name}'. Skipping.")
            continue

        if output_dir:
            dep_target_path.parent.mkdir(parents=True, exist_ok=True)
            if not dep_target_path.exists():
                shutil.copy2(dep_source_path, dep_target_path)
                pc_logging.debug(f"Copied dependency: {dep_source_path} -> {dep_target_path}")
            copied_files.append(str(dep_target_path.relative_to(output_dir)))  # Update dependency path
        else:
            copied_files.append(dep)  # Keep original path if not copied

    return copied_files


def convert_part_action(project: Project, object_name: str, target_format: Optional[str] = None,
                        output_dir: Optional[str] = None, dry_run: bool = False):
    """
    Convert a part to a new format and update its configuration.
    """
    cwd = Path.cwd().resolve()
    output_dir = (cwd / output_dir).resolve() if output_dir else None

    package_name, part_name = resolve_resource_path(project.name, object_name)
    project = project.ctx.get_project(package_name) if project.name != package_name else project
    if not project:
        raise ValueError(f"Project '{package_name}' not found for '{part_name}'")

    part = project.get_part(part_name)
    if not part:
        raise ValueError(f"Part '{part_name}' not found in project '{project.name}'")

    part_config = part.config
    part_type = part_config.get("type")

    if "source" not in part_config and "package" not in part_config and not target_format:
        raise ValueError(f"Part '{part_name}' requires '-t' (target format) to be specified.")

    part_config, source_project, source_part_name = get_final_base_part_config(project, part_config, part_name)
    source_path = get_source_path(source_project, part_config, source_part_name)
    conversion_target = part_config.get("type")

    if dry_run:
        pc_logging.info(f"[Dry Run] No changes made for '{part_name}'.")
        return

    copied_dependencies = []
    converted_path = source_path
    if part_type != conversion_target:
        converted_path = perform_conversion(project, part_name, part_type, part_config,
                                            source_path, conversion_target,
                                            output_dir, copied_dependencies)

    try:
        config_path = converted_path.relative_to(project.path)
    except ValueError:
        config_path = Path("/") / converted_path.relative_to(output_dir)

    updated_config = deep_merge(part_config, {"type": conversion_target, "path": str(config_path)})
    updated_config = update_parameters_with_defaults(updated_config)

    updated_config.pop("package", None)
    updated_config.pop("source", None)
    updated_config.pop("with", None)

    if copied_dependencies:
        updated_config["dependencies"] = [str(dep) for dep in copied_dependencies]

    project.set_part_config(part_name, updated_config)
    pc_logging.debug(f"Updated configuration for '{part_name}': {config_path}")

    if target_format and target_format != conversion_target:
        final_path = perform_conversion(
            project, part_name, conversion_target, updated_config,
            converted_path, target_format, output_dir,
        )

        if final_path is None or not final_path.exists():
            raise ValueError(f"Conversion failed: no output file generated for '{part_name}'.")

        if output_dir:
            try:
                final_config_path = final_path.relative_to(output_dir)
            except ValueError:
                final_config_path = final_path.name
        else:
            final_config_path = final_path.name

        project.update_part_config(part_name, {"type": target_format, "path": str(final_config_path)})
        pc_logging.debug(f"Final updated configuration for '{part_name}': {final_config_path}")

    pc_logging.info(f"Conversion of '{part_name}' completed.")
    return converted_path, updated_config
