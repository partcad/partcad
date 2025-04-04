from pathlib import Path
import rich_click as click

import partcad as pc
from partcad.actions.assembly import import_assy_action
from ...cli_context import CliContext

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
def cli(cli_ctx: CliContext, package: str, assembly_file: str, desc: str):
    """
    CLI command to import an assembly from a file.
    Automatically creates multiple parts and an assembly.
    """
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

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

        pc.logging.info(f"Importing assembly from {assembly_type.upper()} file: {assembly_file}")

        # Get the target package
        package = ctx.resolve_package_path(package)
        package_obj: pc.Project = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return

        config = {"desc": desc} if desc else {}

        try:
            assy_name = import_assy_action(package_obj, assembly_type, assembly_file, config)
            click.echo(f"Assembly '{assy_name}' imported successfully.")
        except Exception as e:
            pc.logging.exception(f"Error importing assembly")
            raise click.ClickException(f"Error importing assembly: {e}") from e
