import rich_click as click
from partcad import logging


@click.command(help="Order from suppliers")
def cli() -> None:
    with logging.Process("SupplyOrder", "this"):
        # TODO-113: Implement Supplier validation
        # TODO-114: Implement Order processing
        # TODO-115: Implement Error handling
        # TODO-116: Implement Success confirmation
        pass
