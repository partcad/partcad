#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ...service import run


@click.command(help="Reset the internal data of the PartCAD daemon")
@click.option(
    "--repo-only",
    is_flag=True,
    help="Reset the cached dependencies only",
    show_envvar=True,
)
@click.option(
    "--sandbox-only",
    is_flag=True,
    help="Reset the sandboxed runtime environments only",
    show_envvar=True,
)
@click.option(
    "--cache-only",
    is_flag=True,
    help="Reset the filesystem cache only",
    show_envvar=True,
)
@click.pass_obj
def cli(cli_ctx, repo_only: bool, sandbox_only: bool, cache_only: bool) -> None:
    """Reset the daemon's internal data.

    The counterpart of `pc system reset`, which only ever touches the machine
    the CLI runs on. The daemon has its own internal state directory and its own
    warm contexts, and clears both. It does so unconditionally: the caller has
    already decided, and a background daemon has nobody to ask.
    """
    run(
        cli_ctx,
        "daemon.reset",
        {"repo_only": repo_only, "sandbox_only": sandbox_only, "cache_only": cache_only},
        span_name="daemon reset",
    )
