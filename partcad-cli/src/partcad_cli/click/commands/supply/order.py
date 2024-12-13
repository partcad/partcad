import rich_click as click
from partcad import logging


@click.command(help="Order from suppliers")
def cli():
    with logging.Process("SupplyOrder", "this"):
        pass
