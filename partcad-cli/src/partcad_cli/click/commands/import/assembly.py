import rich_click as click
import partcad.logging as pc_logging
from partcad.actions.assy_actions import import_assy_action
from partcad.context import Context


@click.command(help="Import an assembly from a file, creating parts and an ASSY.")
@click.argument("file_type", type=click.Choice(["step"]), required=True)
@click.argument("assembly_file", type=str, required=True)
@click.option("--desc", type=str, help="Optional description for the imported assembly.")
@click.pass_obj
def cli(ctx: Context, file_type: str, assembly_file: str, desc: str):
    """
    CLI command to import an assembly from a file.
    Automatically creates multiple parts and an assembly.
    """
    pc_logging.info(f"Importing assembly from {file_type.upper()} file: {assembly_file}")

    project = ctx.get_project("")
    if not project:
        pc_logging.error("Project retrieval failed.")
        raise click.ClickException("Failed to retrieve the project.")

    config = {"desc": desc} if desc else {}

    try:
        assy_name = import_assy_action(project, file_type, assembly_file, config)
        click.echo(f"Assembly '{assy_name}' imported successfully.")
    except Exception as e:
        pc_logging.exception(f"Error importing assembly")
        raise click.ClickException(f"Error importing assembly: {e}") from e
