#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os
from pathlib import Path

import rich_click as click

from partcad_utils.utils import looks_like_url

from ...service import run


@click.command(help="Add software from a file or a URL")
@click.option(
    "--desc",
    "desc",
    type=str,
    help="The software description.",
    required=False,
    show_envvar=True,
)
@click.argument("path", type=str)  # help="Path to the file, or a URL to fetch it from"
@click.pass_context
def cli(click_ctx: click.Context, desc: str | None, path: str):
    """
    CLI command to add software to the package.

    PATH is a file the package already has - a firmware image, a binary, a disk
    image - or an http(s) URL to fetch one from. A URL is fetched once so that
    the declaration can be pinned with the 'fileHash' of what came back, which
    software needs: a piece of software cannot be bought by vendor and SKU, so
    a file it neither carries nor pins is one nothing identifies.

    No type argument: 'raw' is the only one there is, and the types that will
    join it name a firmware flashing procedure rather than a file format.
    """
    cli_ctx = click_ctx.obj

    params = {"obj_kind": "software"}
    if looks_like_url(path):
        params["url"] = path
    else:
        file_path = Path(path)
        if not file_path.exists():
            raise click.UsageError(f"ERROR: The software file '{file_path}' does not exist.")
        # Absolute for the daemon (see add/part.py); reported back
        # package-relative.
        params["path"] = os.path.abspath(path)
    package = click_ctx.parent.params.get("package")
    if package is not None:
        params["package"] = package
    if desc:
        params["desc"] = desc

    result = run(cli_ctx, "add.object", params, span_name="add software", needs_context=True)
    # No result means the daemon rejected the file (e.g. outside the package)
    # and already said why; do not follow that with a success line.
    if result and result.get("name"):
        click.echo(f"Software '{result['name']}' added to the project.")
