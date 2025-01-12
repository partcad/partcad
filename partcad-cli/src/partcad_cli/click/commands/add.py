import os
import rich_click as click
from partcad_cli.click.loader import Loader


class AddCommands(Loader):
    # TODO-91: @alexanderilyin: Use LazyGroup instead: https://click.palletsprojects.com/en/stable/complex/#using-lazygroup-to-define-a-cli
    COMMANDS_FOLDER = os.path.join(Loader.COMMANDS_FOLDER, "add")


@click.command(cls=AddCommands, help="Add a dependency, sketch, part, or assembly")
def cli() -> None:
    pass
