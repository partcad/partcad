#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ..service import run


@click.command(help="""Download everything the package needs to be built.

    Fetches all imported packages, then prepares every sketch, part and assembly:
    each object's cache key is computed, which downloads the files behind
    'fileFrom' and resolves cross-package references, pulling in the packages the
    objects really depend on. Nothing is built. This is the PartCAD counterpart of
    'npm install'.""")
@click.option(
    "--package",
    "-P",
    type=str,
    default="",
    show_envvar=True,
    help="Package to install the objects of (the current one by default)",
)
@click.option(
    "--recursive",
    "-r",
    is_flag=True,
    show_envvar=True,
    help="Also prepare the objects of all imported packages",
)
@click.pass_obj
def cli(cli_ctx, package, recursive) -> None:
    stats = run(
        cli_ctx,
        "install",
        {"package": package, "recursive": recursive},
        span_name="install",
        needs_context=True,
    )
    # The daemon has already reported each failure; turn the counts into a
    # non-zero exit so a script or a CI job notices an incomplete install.
    failed = (stats or {}).get("failed", 0) + (stats or {}).get("failed_packages", 0)
    if failed:
        raise click.ClickException("Failed to install %d objects or packages" % failed)
