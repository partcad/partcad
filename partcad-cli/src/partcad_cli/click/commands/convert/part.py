#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
from partcad.actions.part import convert_part_action
from ...cli_context import CliContext


SUPPORTED_CONVERT_FORMATS = ["step", "brep", "stl", "3mf", "threejs", "obj", "gltf", "iges"]


@click.command(help="Convert parts to another format and update their type.")
@click.argument("object_name", type=str, required=True)
@click.option(
    "-t",
    "--target-format",
    help="Target conversion format.",
    type=click.Choice(SUPPORTED_CONVERT_FORMATS),
    required=False,
)
@click.option(
    "-P",
    "--package",
    help="Package to retrieve the part from",
    type=str,
)
@click.option(
    "-O",
    "--output-dir",
    help="Output directory for converted files.",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
)
@click.option("--dry-run", help="Simulate conversion without making any changes.", is_flag=True)
@click.pass_obj
def cli(cli_ctx: CliContext, object_name: str, target_format: str, package: str, output_dir: str, dry_run: bool):
    """
    CLI command to convert a part to a new format.

    :param cli_ctx: PartCAD context
    :param object_name: Name of the object to convert
    :param target_format: Desired target format
    :param output_dir: (Optional) Output directory for the converted file
    :param dry_run: If True, simulates conversion without actual changes
    """
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        package = ctx.resolve_package_path(package)
        package_obj = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            raise click.UsageError("Failed to retrieve the project.")
        package = package_obj.name  # '//' may end up having a different name

        pc.logging.info(f"Starting conversion: '{object_name}' -> '{target_format}', dry_run={dry_run}")

        try:
            # pc.logging.Process() is done inside "convert_part_action"
            convert_part_action(package_obj, object_name, target_format, output_dir=output_dir, dry_run=dry_run)
        except ValueError as e:
            raise click.UsageError(str(e))

        click.echo(f"Conversion of '{object_name}' completed.")
