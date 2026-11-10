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
    "gltf": ["gltf", "glb"],
    "urdf": ["urdf"],
}


@click.command(help="Import an assembly from a file, creating parts and an ASSY (Assembly YAML).")
@click.argument("assembly_file", type=str, required=True)
@click.option("--desc", type=str, help="Optional description for the imported assembly.")
@click.option(
    "--compound",
    is_flag=True,
    help=(
        "Import the assembly as one part, its compound, instead of a part per item and an ASSY that places them. "
        "A STEP or glTF file is imported as a part of that type, as it is; a URDF as the STEP of its compound."
    ),
)
@click.option(
    "-P",
    "--package",
    help="Package to import the object to",
    type=str,
    default=".",
)
@click.pass_obj
def cli(cli_ctx, package: str, assembly_file: str, desc: str, compound: bool):
    """
    CLI command to import an assembly from a file.
    Automatically creates multiple parts and an assembly.

    A STEP file becomes one part per solid, and a glTF file (`.gltf`, `.glb`)
    one `gltf` part per mesh, in its materials' colours; a URDF becomes one part
    per link plus an interface pair per joint, so the assembly connects its parts
    instead of placing them by coordinates. Either way the package ends up
    holding PartCAD's own objects - `pc add assembly` is what declares a file
    where it lies instead.

    `--compound` imports the whole assembly as one part instead: its compound,
    every item in one shape, in the colours and materials each states.

    Served by the daemon: the reads run in sandboxed wrappers
    (`wrapper_import_assy`, `wrapper_import_urdf`), whose Python runtimes
    belong to the daemon.
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
        # Absolute: the daemon does not share the client's working directory.
        "source": os.path.abspath(assembly_file),
        "assembly_type": assembly_type,
        "package": package,
    }
    if desc:
        params["desc"] = desc
    if compound:
        params["compound"] = True

    result = run(cli_ctx, "import.object", params, span_name="import assembly", needs_context=True)
    name = (result or {}).get("name", file_path.stem)
    if compound:
        click.echo(f"Assembly '{file_path.name}' imported successfully as the part '{name}'.")
    else:
        click.echo(f"Assembly '{name}' imported successfully.")
