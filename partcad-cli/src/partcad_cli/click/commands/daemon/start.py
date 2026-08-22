#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc daemon start` -- ensure this workspace's daemon and print its endpoint.

Also the VS Code extension's way in. The extension does not derive socket paths
or probe liveness itself: it runs this command, reads the endpoint from stdout,
and connects. One implementation of "where is the daemon", in
`partcad_client`, rather than one per language.
"""

import logging
import os

import rich_click as click
from partcad_client import client


@click.command(help="Start the PartCAD daemon for this workspace (if needed) and print its socket path")
def cli() -> None:
    if os.name == "nt":
        click.echo(
            "The PartCAD socket daemon is not available on Windows yet; "
            "commands run a per-invocation service instead."
        )
        return
    path = client.start_daemon(extra_args=daemon_args())
    click.echo(path)


def daemon_args() -> list:
    """The global options that change how a *daemon* behaves, as launcher flags.

    The client's own globals are applied to its `user_config` and stop there, so
    without this a daemon started by `pc --python-sandbox pypy ...` would serve
    with whatever sandbox its own defaults chose. They are read back from
    `user_config` rather than from the click parameters, so a value set in the
    user's configuration file travels as well as one typed on the command line.

    Only ever consulted when a daemon is actually started: one already serving
    the workspace keeps the settings it was started with.
    """
    from partcad_utils.user_config import user_config

    args = []
    if getattr(user_config, "offline", False):
        args.append("--offline")
    if getattr(user_config, "force_update", False):
        args.append("--force-update")
    sandbox = getattr(user_config, "python_sandbox", None)
    if sandbox:
        args.extend(["--python-sandbox", sandbox])
    level = logging.getLogger("partcad").getEffectiveLevel()
    if level <= logging.DEBUG:
        args.append("--verbose")
    elif level > logging.INFO:
        args.append("--quiet")
    return args
