#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ...service import run


@click.option(
    "--repo-only",
    is_flag=True,
    default=False,
    help="Remove the cached repositories only.",
)
@click.option(
    "--sandbox-only",
    is_flag=True,
    default=False,
    help="Remove the sandbox environments only.",
)
@click.option(
    "--cache-only",
    is_flag=True,
    default=False,
    help="Remove the filesystem caches only.",
)
@click.command(help="Reset all internal states maintained by PartCAD")
@click.pass_obj
def cli(cli_ctx, repo_only: bool, sandbox_only: bool, cache_only: bool) -> None:
    run(
        cli_ctx,
        "system.reset",
        {"repo_only": repo_only, "sandbox_only": sandbox_only, "cache_only": cache_only},
        span_name="system reset",
    )
