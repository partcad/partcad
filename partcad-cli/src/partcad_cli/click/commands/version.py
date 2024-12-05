import logging
import partcad as pc
import partcad_cli as pcc
import partcad.logging as pc_logging
import rich_click as click


# TODO: @alexanderilyin: Write test which asserts this command is fast
@click.command(help="Print PartCAD Python Module & PartCAD CLI versions and exit")
def cli():
    pc_logging.info("PartCAD Python Module version: %s" % pc.__version__)
    pc_logging.info("PartCAD CLI version: %s" % pcc.__version__)
