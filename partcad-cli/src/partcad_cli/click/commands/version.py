import partcad as pc
import partcad_cli as pcc
import partcad.logging as logging
import rich_click as click


@click.command(help="Display the versions of the PartCAD Python Module and CLI, then exit")
def cli() -> None:
    logging.info(f"PartCAD Python Module version: {pc.__version__}")
    logging.info(f"PartCAD CLI version: {pcc.__version__}")
