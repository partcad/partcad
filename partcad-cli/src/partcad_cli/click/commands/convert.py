import os
from typing import List, Optional, Tuple

import rich_click as click
import partcad.logging as logging
import partcad.utils as pc_utils
from partcad.context import Context
from partcad import Project
from partcad.conversion import convert_object


@click.command(help="Convert parts, assemblies, or scenes to another format and update their type")
@click.option("-p", "--create-dirs", help="Create necessary directory structure", is_flag=True)
@click.option("-O", "--output-dir", help="Output directory for converted files",
              type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("-t", "--target-format", help="Target conversion format",
              type=click.Choice(["step", "brep", "stl", "3mf", "threejs", "obj", "gltf"]), required=True)
@click.option("-P", "--package", help="Package containing the object", type=str)
@click.option("-r", "--recursive", help="Process packages recursively", is_flag=True)
@click.option("-i", "--in-place", help="Update object's type in place", is_flag=True, default=False)
@click.argument("object", type=str, required=True)
@click.pass_obj
def cli(ctx: Context, create_dirs: bool, output_dir: Optional[str], target_format: str,
        package: Optional[str], recursive: bool, in_place: bool, object: str) -> None:
    """CLI command for conversion."""
    logging.info(f"Starting conversion for '{object}' to '{target_format}', in_place={in_place}")
    try:
        ctx.option_create_dirs = create_dirs
        package = package or ""
        packages = _get_packages(ctx, package, recursive)
        for pkg in packages:
            resolved_package, resolved_object = _resolve_package_object(ctx, pkg, object)
            if not resolved_object:
                raise ValueError("Object must be specified for conversion.")
            project: Project = ctx.get_project(resolved_package)
            logging.info(f"Converting object '{resolved_object}' in project '{project.name}'")
            convert_object(project, resolved_object, target_format, output_dir, in_place)
        logging.info("Conversion finished.")
    except Exception as e:
        logging.error(f"Conversion failed: {e}", exc_info=True)
        raise click.ClickException(f"Conversion failed: {e}") from e

def _get_packages(ctx: Context, package: str, recursive: bool) -> List[str]:
    """Return list of packages to process."""
    if recursive:
        start_package = pc_utils.get_child_project_path(ctx.get_current_project_path(), package)
        all_packages = ctx.get_all_packages(start_package)
        return [pkg["name"] for pkg in all_packages]
    return [package]

def _resolve_package_object(ctx: Context, package: str, object_str: str) -> Tuple[str, str]:
    """Resolve package and object from the provided string."""
    if ":" not in object_str:
        object_str = f":{object_str}"
    resolved_package, resolved_object = pc_utils.resolve_resource_path(ctx.get_current_project_path() + package, object_str)
    return resolved_package, resolved_object
