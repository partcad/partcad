import rich_click as click
from partcad import logging


@click.command(help="Order from suppliers")
def cli() -> None:
    with logging.Process("SupplyOrder", "this"):
        # TODO: Implement Supplier validation
        # TODO: Implement Order processing
        # TODO: Implement Error handling
        # TODO: Implement Success confirmation
        pass
