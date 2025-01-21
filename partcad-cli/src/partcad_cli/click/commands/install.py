import rich_click as click
from partcad.logging import Process, info
from partcad.context import Context
from partcad.user_config import user_config
from partcad.sentry import tracer as pc_tracer


@click.command(help="Download and set up all imported packages")
@click.pass_obj
@pc_tracer.start_as_current_span("Command [pc install]")
def cli(ctx: Context) -> None:
    # TODO-100: @alexanderilyin: Use something like 'click.command.name'
    with Process("Install", "this"):
        user_config.force_update = True
        ctx.get_all_packages()
        if ctx.stats_git_ops:
            info(f"Git operations: {ctx.stats_git_ops}")
