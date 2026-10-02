#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from partcad_client import daemon


@click.command(help="Stop the PartCAD daemon serving this workspace, or with --all every one on this machine")
@click.option(
    "--all",
    "stop_all",
    is_flag=True,
    help="Stop every PartCAD daemon running on this machine and wait for each to exit",
)
def cli(stop_all: bool) -> None:
    if stop_all:
        _stop_all()
        return
    # `stop_daemon` knows both transports -- the AF_UNIX socket and the Windows
    # named pipe -- so there is nothing to decide here. It answered Windows with
    # "nothing to stop" while `pc daemon start` was starting one.
    if daemon.stop_daemon():
        click.echo("PartCAD daemon stopped")
    else:
        click.echo("No PartCAD daemon was running for this workspace")


def _stop_all() -> None:
    """What an uninstaller runs before it removes the files a daemon runs from.

    A daemon is started per workspace and outlives whatever started it -- the
    editor, a `pc` command -- so removing an installation can find one or more
    of them still executing out of it. On Windows that makes the removal fail:
    an executable that is running cannot be deleted. This is `pc upgrade`'s way
    of stopping them (see `partcad_client.daemon.stop_all_daemons`), asked for
    by name: each daemon is told to stop and then waited for, which a kill
    would not do.

    Exits non-zero when a daemon did not go, so that the caller knows to deal
    with it before deleting anything.
    """
    running = daemon.live_daemon_dirs()
    if not running:
        click.echo("No PartCAD daemon was running")
        return
    stopped = daemon.stop_all_daemons()
    click.echo("Stopped %d of %d PartCAD daemon(s)" % (len(stopped), len(running)))
    if len(stopped) < len(running):
        raise click.ClickException("%d PartCAD daemon(s) did not stop" % (len(running) - len(stopped)))
