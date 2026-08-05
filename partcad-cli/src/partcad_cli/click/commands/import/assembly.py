#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
from pathlib import Path

import rich_click as click

from ...service import run

# assembly_type: [file_extensions]
SUPPORTED_ASSEMBLY_FORMATS_WITH_EXT = {
    "step": ["step", "stp"],
}


@click.command(help="Import an assembly from a file, creating parts and an ASSY (Assembly YAML).")
@click.argument("assembly_file", type=str, required=True)
@click.option("--desc", type=str, help="Optional description for the imported assembly.")
@click.option(
    "-P",
    "--package",
    help="Package to import the object to",
    type=str,
    default=".",
)
@click.pass_obj
def cli(cli_ctx, package: str, assembly_file: str, desc: str):
    """
    CLI command to import an assembly from a file.
    Automatically creates multiple parts and an assembly.
    """
    file_path = Path(assembly_file)
    if not file_path.exists():
        raise click.UsageError(f"File '{assembly_file}' not found.")

    assembly_type = None
    detected_ext = file_path.suffix.lstrip(".").lower()
    for supported_type in SUPPORTED_ASSEMBLY_FORMATS_WITH_EXT.keys():
        if detected_ext in SUPPORTED_ASSEMBLY_FORMATS_WITH_EXT[supported_type]:
            assembly_type = supported_type

    if not assembly_type:
        raise click.ClickException(
            f"Cannot determine file type for '{assembly_file}'. "
            f"Supported assembly types: {', '.join(set(SUPPORTED_ASSEMBLY_FORMATS_WITH_EXT.keys()))}. "
        )

    params = {
        "obj_kind": "assembly",
        "source": os.path.abspath(assembly_file),
        "assembly_type": assembly_type,
        "package": package,
    }
    if desc:
        params["desc"] = desc

    result = run(cli_ctx, "import.object", params, span_name="import assembly", needs_context=True)
    assy_name = (result or {}).get("name", file_path.stem)
    click.echo(f"Assembly '{assy_name}' imported successfully.")
