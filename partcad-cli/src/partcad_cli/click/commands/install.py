import rich_click as click
from partcad.logging import Process, info
from partcad.context import Context


@click.command(help="Download and set up all imported packages")
@click.pass_obj
def cli(ctx: Context) -> None:
    # TODO-100: @alexanderilyin: Use something like 'click.command.name'
    with Process("Install", "this"):
        ctx.user_config.force_update = True
        ctx.get_all_packages()
        if ctx.stats_git_ops:
            info(f"Git operations: {ctx.stats_git_ops}")
