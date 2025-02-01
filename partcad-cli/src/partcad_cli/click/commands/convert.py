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
# @click.option("-r", "--recursive", help="Process packages recursively", is_flag=True)
@click.option("-i", "--in-place", help="Update object's type in place", is_flag=True, default=False)
@click.option("--dry-run", help="Simulate conversion without making any changes", is_flag=True)
@click.argument("object", type=str, required=True)
@click.pass_obj
def cli(ctx: Context, create_dirs: bool, output_dir: Optional[str], target_format: str,
        package: Optional[str], in_place: bool, dry_run: bool, object: str) -> None:
    """CLI command for conversion."""
    logging.info(f"Starting conversion for '{object}' to '{target_format}', in_place={in_place}, dry_run={dry_run}")
    try:
        ctx.option_create_dirs = create_dirs
        package = package or ""

        # NOTE: will add recursion feature later
        # packages = _get_packages(ctx, package, recursive)
        packages = _get_packages(ctx, package)
        for pkg in packages:
            resolved_package, resolved_object = _resolve_package_object(ctx, pkg, object)
            if not resolved_object:
                raise ValueError("Object must be specified for conversion.")
            project: Project = ctx.get_project(resolved_package)
            logging.info(f"Processing object '{resolved_object}' in project '{project.name}'")
            if dry_run:
                # Retrieve original file name from the part configuration.
                part_config = project.get_part_config(resolved_object)
                old_path = part_config.get("path")
                if old_path:
                    base_file_name = os.path.splitext(os.path.basename(old_path))[0]
                    old_ext = os.path.splitext(old_path)[1]
                    old_file = f"{base_file_name}{old_ext}"
                else:
                    old_file = resolved_object
                    base_file_name = resolved_object
                new_file = f"{base_file_name}.{target_format}"
                out_dir_msg = output_dir if output_dir is not None else project.path
                in_place_msg = "update configuration in place" if in_place else "not update configuration"
                logging.info(
                    f"Dry run: would convert object '{old_file}' to '{new_file}' using output directory "
                    f"'{out_dir_msg}' and {in_place_msg}."
                )
            else:
                convert_object(project, resolved_object, target_format, output_dir, in_place)
        logging.info("Conversion finished.")
    except Exception as e:
        logging.error(f"Conversion failed: {e}", exc_info=True)
        raise click.ClickException(f"Conversion failed: {e}") from e


def _get_packages(ctx: Context, package: str, recursive: bool = False) -> List[str]:
    """Return list of packages to process."""
    # If no package is provided, use the current project path.
    if not package:
        full_package = ctx.get_current_project_path()
    else:
        # If package starts with '/', treat it as relative to the project root.
        if package.startswith("/"):
            full_package = os.path.join(ctx.get_current_project_path(), package[1:])
        else:
            full_package = os.path.join(ctx.get_current_project_path(), package)

    # NOTE: will add recursion feature later
    # if recursive:
    #     all_packages = ctx.get_all_packages(full_package)
    #     return [pkg["name"] for pkg in all_packages]
    # else:
        # return [full_package]

    return [full_package]


def _resolve_package_object(ctx: Context, package: str, object_str: str) -> Tuple[str, str]:
    """Resolve package and object from the provided string."""
    # Compute full package path in the same way as _get_packages.
    if not package:
        full_package = ctx.get_current_project_path()
    else:
        if package.startswith("/"):
            full_package = os.path.join(ctx.get_current_project_path(), package[1:])
        else:
            full_package = os.path.join(ctx.get_current_project_path(), package)
    if ":" not in object_str:
        object_str = f":{object_str}"
    resolved_package, resolved_object = pc_utils.resolve_resource_path(full_package, object_str)
    return resolved_package, resolved_object
