import os
import rich_click as click
import partcad.logging as logging
import partcad.utils as pc_utils
from partcad.context import Context
from partcad import Project
from typing import List, Optional, Tuple
import yaml  # May be used for further configuration handling if needed


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
    ctx: Context,
    create_dirs: bool,
    output_dir: Optional[str],
    target_format: str,
    package: Optional[str],
    recursive: bool,
    in_place: bool,
    object: str,
) -> None:
    """
    CLI command to convert parts, assemblies, or scenes.

    This command processes the specified object and converts it to the target format.
    If an output directory is provided, the converted file will be created there.
    When the in-place flag is set, the object's configuration will be updated accordingly.
    """
    logging.info(
        f"Starting 'pc convert' with object='{object}', target_format='{target_format}', in_place={in_place}"
    )

    try:
        # Set context option for creating directories
        ctx.option_create_dirs = create_dirs

        # Retrieve list of packages to process
        package = package or ""
        packages = _get_packages(ctx, package, recursive)
        logging.debug(f"Packages to process: {packages}")

        # Process each package
        for pkg in packages:
            resolved_package, resolved_object = _resolve_package_object(ctx, pkg, object)
            logging.debug(f"Resolved package: '{resolved_package}', object: '{resolved_object}'")

            if not resolved_object:
                raise ValueError("Object must be specified for conversion.")

            project: Project = ctx.get_project(resolved_package)
            logging.info(f"Attempting to convert object '{resolved_object}' in project '{project.name}'.")

            _convert_object(project, resolved_object, target_format, output_dir, in_place)

        logging.info("Finished 'pc convert' command.")

    except Exception as e:
        logging.error(f"Conversion failed: {e}", exc_info=True)
        raise click.ClickException(f"Conversion failed: {e}") from e


def _get_packages(ctx: Context, package: str, recursive: bool) -> List[str]:
    """
    Retrieve a list of packages to process.
    If recursive is True, all child packages starting from the given package path are returned.
    """
    if recursive:
        start_package = pc_utils.get_child_project_path(ctx.get_current_project_path(), package)
        all_packages = ctx.get_all_packages(start_package)
        package_names = [pkg["name"] for pkg in all_packages]
        logging.debug(f"Recursive lookup from '{start_package}' found packages: {package_names}")
        return package_names

    logging.debug(f"Non-recursive package processing for package: '{package}'")
    return [package]


def _resolve_package_object(ctx: Context, package: str, object_str: str) -> Tuple[str, str]:
    """
    Resolve the package and object if provided in 'package:object' format.
    Returns a tuple (resolved_package, resolved_object).
    """
    # Ensure object_str is in the expected format (":object") if package is not specified in the argument
    if ":" not in object_str:
        object_str = f":{object_str}"
    resolved_package, resolved_object = pc_utils.resolve_resource_path(
        ctx.get_current_project_path() + package, object_str
    )
    logging.info(f"Resolved object '{resolved_object}' in package '{resolved_package}'")
    return resolved_package, resolved_object


def _get_object_type(project: Project, object_str: str) -> Tuple[List[str], List[str], List[str]]:
    """
    Determine the type of the object (parts, assemblies, sketches) in the project.
    Returns a tuple of lists: (parts, assemblies, sketches).
    """
    if object_str in project.parts:
        return [object_str], [], []
    elif object_str in project.assemblies:
        return [], [object_str], []
    elif object_str in project.sketches:
        return [], [], [object_str]
    else:
        logging.error(f"Object '{object_str}' not found in parts, assemblies, or sketches.")
        raise ValueError(f"Object '{object_str}' not found in parts, assemblies, or sketches.")


def _convert_object(
    project: Project,
    object_str: str,
    target_format: str,
    output_dir: Optional[str],
    in_place: bool,
) -> None:
    """
    Convert the specified object to the target format and update its configuration if necessary.

    Parameters:
        project (Project): The project instance.
        object_str (str): The object name to convert.
        target_format (str): The target format (e.g., 'step', 'brep', etc.).
        output_dir (Optional[str]): Output directory for the converted file.
        in_place (bool): Whether to update the object's configuration in place.
    """
    try:
        # Identify the type of the object
        parts, assemblies, sketches = _get_object_type(project, object_str)
        logging.info(f"Converting object '{object_str}' to format '{target_format}'")

        # Retrieve current configuration for the object
        part_config = project.get_part_config(object_str)
        old_path = part_config.get("path", None)

        # Determine base file name (without extension)
        base_file_name = os.path.splitext(os.path.basename(old_path))[0] if old_path else object_str
        new_file_name = f"{base_file_name}.{target_format}"

        # Determine output directory for conversion:
        if output_dir:
            # Use the provided output directory as is
            full_output_dir = output_dir
        else:
            if old_path:
                # If old_path is relative, assume it's relative to project.path
                if os.path.isabs(old_path):
                    full_output_dir = os.path.dirname(old_path)
                else:
                    full_output_dir = os.path.join(project.path, os.path.dirname(old_path))
            else:
                # Default to the project's directory
                full_output_dir = project.path

        # Construct the full new file path (including file name)
        new_path = os.path.join(full_output_dir, new_file_name)

        logging.info(f"New path: {new_path}")
        logging.debug(f"Output directory for conversion: {full_output_dir}")

        # Perform the conversion operation.
        # Note: output_dir argument is the full file path (with file name)
        project.convert(
            sketches=sketches,
            interfaces=[],  # Placeholder if interfaces are needed in future
            parts=parts,
            assemblies=assemblies,
            target_format=target_format,
            output_dir=new_path,
            in_place=in_place,
        )

        # Calculate configuration path relative to project root, if applicable.
        abs_project_path = os.path.abspath(project.path)
        abs_new_path = os.path.abspath(new_path)
        if abs_new_path.startswith(abs_project_path):
            config_path = os.path.relpath(abs_new_path, abs_project_path)
        else:
            config_path = new_path

        # Update the part configuration if required
        if in_place or output_dir:
            logging.info(
                f"Updating configuration for object '{object_str}' with type '{target_format}' and path '{config_path}'"
            )
            project.update_part_config(object_str, {"type": target_format, "path": config_path})
            logging.info(
                f"Configuration updated for object '{object_str}': type='{target_format}', path='{config_path}'"
            )

    except Exception as e:
        logging.error(f"Error during conversion of object '{object_str}': {e}", exc_info=True)
        raise RuntimeError(f"Error during conversion: {e}") from e
