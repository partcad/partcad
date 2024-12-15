import logging
import partcad as pc
import partcad_cli as pcc
import partcad.logging as pc_logging
import rich_click as click


# TODO: @alexanderilyin: Write test which asserts this command is fast
@click.command(help="Display the versions of the PartCAD Python Module and CLI, then exit")
def cli():
    pc_logging.info("PartCAD Python Module version: %s" % pc.__version__)
    pc_logging.info("PartCAD CLI version: %s" % pcc.__version__)
