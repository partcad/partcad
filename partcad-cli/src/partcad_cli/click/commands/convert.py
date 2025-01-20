import rich_click as click
import partcad.logging as logging
import partcad.utils as pc_utils
from partcad import Project
from typing import List, Optional, Tuple


@click.command(help="Convert parts, assemblies, or scenes to another format and update their type")
@click.option(
    "-p",
    "--create-dirs",
    help="Create the necessary directory structure if it is missing",
    is_flag=True,
)
@click.option(
    "-O",
    "--output-dir",
    help="Output directory for converted files",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
)
@click.option(
    "-t",
    "--target-format",
    help="Target format to convert to",
    type=click.Choice(["step", "brep", "stl", "3mf", "threejs", "obj", "gltf"]),
    required=True,
)
@click.option(
    "-P",
    "--package",
    help="Specify the package containing the object",
    type=str,
)
@click.option(
    "-r",
    "--recursive",
    help="Recursively process all imported packages",
    is_flag=True,
)
@click.option(
    "-i",
    "--in-place",
    help="Update the object's type in place after conversion",
    is_flag=True,
    default=False,
)
@click.argument("object", type=str, required=True)
@click.pass_obj
def cli(
    ctx: object,
    create_dirs: bool,
    output_dir: Optional[str],
    target_format: str,
    package: Optional[str],
    recursive: bool,
    in_place: bool,
    object: str,
) -> None:
    """CLI command to convert parts, assemblies, or scenes."""
    logging.info(f"Starting 'pc convert' with object={object}, target_format={target_format}, in_place={in_place}")

    # Set options for creating directories
    ctx.option_create_dirs = create_dirs

    # Get the list of packages to process
    package = package or ""
    packages = _get_packages(ctx, package, recursive)

    # Process each package
    for pkg in packages:
        package, object = _resolve_package_object(ctx, pkg, object)

        if not object:
            raise click.UsageError("Object must be specified for conversion.")

        project: Project = ctx.get_project(package)
        _convert_object(project, object, target_format, output_dir, in_place)

    logging.info("Finished 'pc convert' command.")


def _get_packages(ctx: object, package: str, recursive: bool) -> List[str]:
    """Retrieve a list of packages to process."""
    if recursive:
        start_package = pc_utils.get_child_project_path(ctx.get_current_project_path(), package)
        all_packages = ctx.get_all_packages(start_package)
        return [pkg["name"] for pkg in all_packages]
    return [package]


def _resolve_package_object(ctx: object, package: str, object: str) -> Tuple[str, str]:
    """Resolve the package and object if provided in 'package:object' format."""
    if ":" not in object:
        object = f":{object}"
    package, object = pc_utils.resolve_resource_path(ctx.get_current_project_path() + package, object)
    logging.info(f"Resolved object '{object}' in package '{package}'")
    return package, object


def _get_object_type(project: Project, object: str) -> Tuple[List[str], List[str], List[str]]:
    """Determine the type of the object (parts, assemblies, sketches)."""
    if object in project.parts:
        return [object], [], []
    elif object in project.assemblies:
        return [], [object], []
    elif object in project.sketches:
        return [], [], [object]
    else:
        raise click.UsageError(f"Object '{object}' not found in parts, assemblies, or sketches.")


def _convert_object(
    project: Project,
    object: str,
    target_format: str,
    output_dir: Optional[str],
    in_place: bool,
) -> None:
    """Perform the conversion of the specified object."""
    parts, assemblies, sketches = _get_object_type(project, object)

    logging.info(f"Converting object '{object}' to format '{target_format}'")

    # Perform the conversion
    project.convert(
        sketches=sketches,
        interfaces=[],
        parts=parts,
        assemblies=assemblies,
        target_format=target_format,
        output_dir=output_dir,
        in_place=in_place,
    )

    # Update configuration if in-place is enabled
    if in_place:
        logging.info(f"Updating configuration for object '{object}' to type '{target_format}'")
        project.update_part_config(object, {"type": target_format})
