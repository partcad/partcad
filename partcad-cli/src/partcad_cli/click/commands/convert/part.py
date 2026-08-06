#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ...service import run


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
def cli(cli_ctx, object_name: str, target_format: str, package: str, output_dir: str, dry_run: bool):
    """CLI command to convert a part to a new format."""
    run(
        cli_ctx,
        "convert.object",
        {
            "kind": "part",
            "object_name": object_name,
            "target_format": target_format,
            "package": package,
            # Resolve to absolute so output lands in the user's cwd, not the daemon's.
            "output_dir": os.path.abspath(output_dir) if output_dir else None,
            "dry_run": dry_run,
        },
        needs_context=True,
    )
