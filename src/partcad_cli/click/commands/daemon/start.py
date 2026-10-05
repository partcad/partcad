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

import rich_click as click

from partcad_client import client


@click.command(help="Start the PartCAD daemon for this workspace (if needed) and print its endpoint")
def cli() -> None:
    # Every platform, including Windows: the daemon is an AF_UNIX socket on
    # POSIX and a named pipe there (`partcad_service_json_rpc.daemon`
    # implements both), and the endpoint is printed the same way either way.
    # This used to answer Windows with a sentence saying there was no daemon --
    # on stdout, with a zero exit status, which is where the endpoint goes. The
    # editor extension connected to the sentence.
    #
    # `replace_different`: this command is asked for a daemon started a
    # particular way -- the extension's settings arrive as these globals and
    # nowhere else -- so one already running some other way is restarted
    # rather than handed back with the flags dropped.
    click.echo(client.start_daemon(extra_args=daemon_args(), replace_different=True))


def daemon_args() -> list:
    """The global options that change how a *daemon* behaves, as launcher flags.

    The client's own globals are applied to its `user_config` and stop there, so
    without this a daemon started by `pc --python-sandbox pypy ...` would serve
    with whatever sandbox its own defaults chose. They are read back from
    `user_config` rather than from the click parameters, so a value set in the
    user's configuration file travels as well as one typed on the command line.

    A daemon already serving the workspace with other settings is restarted
    with these (see `cli` above).
    """
    from partcad_utils.user_config import user_config

    args = []
    if getattr(user_config, "offline", False):
        args.append("--offline")
    if getattr(user_config, "force_update", False):
        args.append("--force-update")
    # Only a sandbox somebody chose. `python_sandbox` always has a value --
    # conda where the host has it, venv otherwise -- because that is the
    # fallback; forwarding it made it a *stated* choice on the daemon, and a
    # stated sandbox is obeyed, so the daemon never got to prefer Docker.
    if getattr(user_config, "python_sandbox_declared", False):
        args.extend(["--python-sandbox", user_config.python_sandbox])
    level = logging.getLogger("partcad").getEffectiveLevel()
    if level <= logging.DEBUG:
        args.append("--verbose")
    elif level > logging.INFO:
        args.append("--quiet")
    return args
