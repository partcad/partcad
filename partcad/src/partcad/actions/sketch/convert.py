from pathlib import Path
import shutil
import time
from typing import Optional

import partcad.logging as pc_logging
from partcad.project import Project
from partcad.shape import SKETCH_EXTENSION_MAPPING
from partcad.utils import resolve_resource_path


FILE_BASED_SKETCHES = ["dxf", "svg"]
SHALLOW_COPY_SKETCH_TYPES = ["alias", "enrich"]


def parse_parameters_from_source(source_value: str) -> tuple[str, dict]:
    """Extract parameters from the source name string."""
    if ";" in source_value:
        base_source, params_str = source_value.split(";", 1)
        parameters = {}
        for param in params_str.split(","):
            key, value = param.split("=")
            parameters[key] = float(value) if "." in value else int(value)
        return base_source, parameters
    return source_value, {}


def get_final_base_sketch_config(project: Project, sketch_config: dict, sketch_name: str):
    visited = set()
    final_params = {}

    while sketch_config.get("type") in SHALLOW_COPY_SKETCH_TYPES:
        source_key = "source_resolved" if "source_resolved" in sketch_config else "source"
        if source_key not in sketch_config:
            break

        source_value = sketch_config[source_key]
        base_source, params = parse_parameters_from_source(source_value)

        if base_source in visited:
            raise ValueError(f"Circular reference detected in sketch '{sketch_name}'")

        visited.add(base_source)

        if "with" in sketch_config:
            final_params.update(sketch_config["with"])

        base_package, base_sketch_name = resolve_resource_path(project.name, base_source)
        base_project = project.ctx.get_project(base_package)

        if not base_project:
            raise ValueError(f"Base project '{base_package}' not found for sketch '{sketch_name}'")

        base_sketch_config = base_project.get_sketch_config(base_sketch_name)

        if not base_sketch_config:
            raise ValueError(f"Sketch config for '{base_sketch_name}' not found in '{base_project.name}'")

        pc_logging.debug(f"Resolving sketch '{sketch_name}' -> '{base_sketch_name}' (source: '{base_source}')")

        sketch_config = base_sketch_config
        project = base_project
        sketch_name = base_sketch_name

        # Merge parameters into the current sketch config
        if params:
            sketch_config["parameters"] = {**sketch_config.get("parameters", {}), **params}

    if final_params:
        sketch_config.setdefault("with", {}).update(final_params)

    return sketch_config, project, sketch_name


def convert_sketch_action(
    project: Project,
    object_name: str,
    target_format: Optional[str] = None,
    output_dir: Optional[str] = None,
    dry_run: bool = False,
):
    """
    Convert a sketch to a new format and update its configuration.
    """
    cwd = Path.cwd().resolve()
    output_dir = (cwd / output_dir).resolve() if output_dir else None

    package_name, sketch_name = resolve_resource_path(project.name, object_name)
    project = project.ctx.get_project(package_name) if project.name != package_name else project
    if not project:
        raise ValueError(f"Project '{package_name}' not found for sketch '{sketch_name}'")

    sketch = project.get_sketch(sketch_name)
    if not sketch:
        raise ValueError(f"Sketch '{sketch_name}' not found in project '{project.name}'")

    sketch_config = sketch.config
    sketch_type = sketch_config.get("type")

    if "source" not in sketch_config and not target_format:
        raise ValueError(f"Sketch '{sketch_name}' requires '-t' (target format) to be specified.")

    if dry_run:
        pc_logging.info(f"[Dry Run] No changes made for '{sketch_name}'.")
        return

    sketch_config, source_project, source_sketch_name = get_final_base_sketch_config(
        project, sketch_config, sketch_name
    )
    source_type = sketch_config.get("type")

    source_ext = SKETCH_EXTENSION_MAPPING.get(source_type, source_type)
    if "path" in sketch_config:
        source_path = (Path(source_project.path) / sketch_config["path"]).resolve()
    else:
        source_path = Path(source_project.config_dir) / f"{source_sketch_name}.{source_ext}"

    if source_type in FILE_BASED_SKETCHES and not source_path.exists():
        raise FileNotFoundError(f"Source sketch file '{source_path}' does not exist.")

    intermediate_type = source_type
    output_ext = SKETCH_EXTENSION_MAPPING.get(target_format or intermediate_type, intermediate_type)
    if output_dir:
        output_path = Path(output_dir) / f"{sketch_name}.{output_ext}"
    else:
        output_path = Path(project.path) / f"{sketch_name}.{output_ext}"

    converted_path = source_path
    new_config = None

    if sketch_type != source_type:
        if output_path.exists() and source_path.samefile(output_path):
            pc_logging.warning(f"Skipping conversion: source and target paths are identical ({source_path}).")
        else:
            pc_logging.info(f"Converting sketch '{sketch_name}': {sketch_type} -> {source_type} ({output_path})")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, output_path)
        converted_path = output_path

        try:
            config_path = output_path.relative_to(project.path)
        except ValueError:
            if output_dir:
                config_path = Path("/") / output_path.relative_to(output_dir)
            else:
                config_path = output_path.name

        new_config = {
            "type": source_type,
            "path": str(config_path),
            "manufacturable": True,
        }
        project.set_sketch_config(sketch_name, new_config)
        pc_logging.debug(f"Final config for sketch '{sketch_name}': {new_config}")

    if target_format and target_format != source_type:
        final_output_path = (
            Path(output_dir or project.path)
            / f"{sketch_name}.{SKETCH_EXTENSION_MAPPING.get(target_format, target_format)}"
        )
        pc_logging.info(
            f"Converting sketch '{sketch_name}': '{source_type}' -> '{target_format}' ({final_output_path})"
        )
        with pc_logging.Process("Convert", sketch_name):
            project.render(
                sketches=[sketch_name],
                interfaces=[],
                parts=[],
                assemblies=[],
                format=target_format,
                output_dir=str(final_output_path.parent),
            )
        if not final_output_path.exists():
            raise RuntimeError(f"Conversion failed: output file '{final_output_path}' was not created.")

        try:
            config_path = final_output_path.relative_to(project.path)
        except ValueError:
            if output_dir:
                config_path = Path("/") / final_output_path.relative_to(output_dir)
            else:
                config_path = final_output_path.name

        new_config = {
            "type": target_format,
            "path": str(config_path),
            "manufacturable": True,
        }
        project.set_sketch_config(sketch_name, new_config)
        pc_logging.debug(f"Final config for sketch '{sketch_name}': {new_config}")

        return final_output_path, new_config

    return converted_path, new_config
