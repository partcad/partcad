from pathlib import Path
import rich_click as click
from partcad.assembly_types import AssemblyTypes
import partcad.logging as pc_logging
from partcad.actions.assembly import import_assy_action
from partcad.context import Context


SUPPORTED_ASSEMBLY_FORMATS_WITH_EXT = AssemblyTypes.importable.as_dict()

@click.command(help="Import an assembly from a file, creating parts and an ASSY (Assembly YAML).")
@click.argument("assembly_file", type=str, required=True)
@click.option("--desc", type=str, help="Optional description for the imported assembly.")
@click.pass_obj
def cli(ctx: Context, assembly_file: str, desc: str):
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

    pc_logging.info(f"Importing assembly from {assembly_type.upper()} file: {assembly_file}")

    project = ctx.get_project("")
    if not project:
        pc_logging.error("Project retrieval failed.")
        raise click.ClickException("Failed to retrieve the project.")

    config = {"desc": desc} if desc else {}

    try:
        assy_name = import_assy_action(project, assembly_type, assembly_file, config)
        click.echo(f"Assembly '{assy_name}' imported successfully.")
    except Exception as e:
        pc_logging.exception(f"Error importing assembly")
        raise click.ClickException(f"Error importing assembly: {e}") from e
