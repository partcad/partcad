import rich_click as click
from partcad.logging import Process
from partcad.context import Context
from partcad.user_config import user_config


@click.command(help="Download and set up all imported packages")
@click.pass_obj  # partcad
@click.pass_context  # click
def cli(click: click.Context, partcad: Context):
    # TODO: @alexanderilyin: Use something like 'click.command.name'
    with Process("Install", "this"):
        user_config.force_update = True
        partcad.get_all_packages()
