from pathlib import Path
from typing import Optional

import partcad.logging as pc_logging
from partcad.project import Project
from partcad.shape import PART_EXTENSION_MAPPING
from partcad.utils import resolve_resource_path

FILE_BASED_SKETCHES = ["dxf", "svg"]


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
    # pc_logging.info(project.sketches)
    if not project:
        raise ValueError(f"Project '{package_name}' not found for sketch '{sketch_name}'")

    sketch = project.get_sketch(sketch_name)
    if not sketch:
        raise ValueError(f"Sketch '{sketch_name}' not found in project '{project.name}'")

    sketch_config = sketch.config
    sketch_type = sketch_config.get("type")

    if not target_format:
        raise ValueError(f"Sketch '{sketch_name}' requires '-t' (target format) to be specified.")

    if dry_run:
        pc_logging.info(f"[Dry Run] Would convert sketch '{sketch_name}' to '{target_format}'.")
        return

    source_ext = PART_EXTENSION_MAPPING.get(sketch_type, sketch_type)
    target_ext = PART_EXTENSION_MAPPING.get(target_format, target_format)

    if "path" in sketch_config:
        source_path = (Path(project.path) / sketch_config["path"]).resolve()
    else:
        source_path = Path(project.config_dir) / f"{sketch_name}.{source_ext}"


    if sketch_type in FILE_BASED_SKETCHES and not source_path.exists():
        raise FileNotFoundError(f"Source sketch file '{source_path}' does not exist.")

    if output_dir:
        output_path = Path(output_dir).resolve() / f"{sketch_name}.{target_ext}"
    else:
        output_path = Path(project.path) / f"{sketch_name}.{target_ext}"

    if output_path.exists() and source_path.samefile(output_path):
        pc_logging.warning(f"Skipping conversion: source and target paths are identical ({source_path}).")
        return output_path

    pc_logging.info(f"Converting sketch '{sketch_name}': {sketch_type} -> {target_format} ({output_path})")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pc_logging.Process("Convert", sketch_name):
        project.render(
            sketches=[sketch_name],
            interfaces=[],
            parts=[],
            assemblies=[],
            format=target_format,
            output_dir=str(output_path.parent),
        )
        # sketch.render(
        #   ctx=project.ctx,
        #   target_format=target_format,
        #   project=project,
        #   filepath=
        #   )

    if not output_path.exists():
        raise RuntimeError(f"Conversion failed: output file '{output_path}' was not created.")

    try:
        config_path = output_path.relative_to(project.path)
    except ValueError:
        config_path = Path("/") / output_path.relative_to(output_dir)

    new_config = {
        "type": target_format,
        "path": str(config_path),
    }

    project.set_sketch_config(sketch_name, new_config)
    pc_logging.debug(f"Updated configuration for sketch '{sketch_name}': {new_config}")
    pc_logging.info(f"Conversion of sketch '{sketch_name}' is completed.")

    return output_path, new_config
