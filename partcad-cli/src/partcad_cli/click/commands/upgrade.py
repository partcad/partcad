#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc upgrade` -- bring the PartCAD installation itself up to date.

The host-level counterpart of `pc update`, which refetches the packages a
package imports. This one updates PartCAD: the Python wheels, or the standalone bundle
that carries its own interpreter. The two are deliberately separate commands
because they act on different things -- one on a package, one on the machine --
and a user upgrading their tools should not have their package graph refetched,
nor the other way round.

It runs **in the client process**, which is where it has to run. Upgrading an
installation is a client-side act: it is this machine's copy of PartCAD being
replaced, by the process running from it. A daemon must not do it -- a daemon can
be remote, where "upgrade PartCAD" would mean upgrading somebody else's
installation.

This command owns the daemon handling the upgrade needs, because the upgrader
deliberately has none. **Every** daemon running on this machine executes the files
about to be replaced, so every one of them is asked to stop and waited for -- but
only once a newer version has been found, so a no-op `pc upgrade` never costs
anybody their warm context. Doing that from a client is what makes it simple: one
process, acting on the machine it runs on, rather than daemons trying to police
each other.

Any daemon that outlives the stop is not fatal. The new version is installed
beside the old one, so a survivor keeps serving from intact files -- and the old
bundle is not removed until this command exits, by which time the survivor is the
only thing that could still be reading it.
"""

import rich_click as click
from partcad_client_utils import selfupdate


@click.command(help="Upgrade PartCAD itself to the latest version.")
@click.option(
    "--check",
    is_flag=True,
    help="Report whether a newer PartCAD is available, without installing anything.",
)
@click.option(
    "--to-version",
    type=str,
    default=None,
    metavar="VERSION",
    help="Install this version of PartCAD instead of the latest one.",
)
def cli(check: bool, to_version: str) -> None:
    from partcad_utils.user_config import user_config

    if user_config.offline:
        # `--offline` is a promise that nothing is fetched, and looking a release
        # up is a fetch. Reported rather than failed: `--offline` is often a
        # standing setting rather than something typed on this command line, and
        # failing a scripted `pc upgrade` for it would be a surprise.
        click.echo("Offline mode: skipping the PartCAD version check.")
        return

    try:
        if check:
            _report_check(selfupdate.check(to_version=to_version))
            return
        # `update` narrates itself through the log callback: what it found and
        # where the new version landed. `before_install` runs in between, once
        # something newer is confirmed and before anything is written.
        result = selfupdate.update(to_version=to_version, log=click.echo, before_install=_stop_local_daemons)
        if result.get("updated"):
            # This process is still the version it started as; the next `pc` is
            # not. Saying so beats a `pc version` that disagrees with the line
            # printed a second ago.
            click.echo("This command is still running the previous version; the new one runs from now on.")
    except selfupdate.SelfUpdateError as e:
        raise click.ClickException(str(e))


def _stop_local_daemons() -> None:
    """Stop every daemon running on this machine and wait for them to be gone.

    Run just before the new version is written, because each one is executing
    files that are about to be replaced. Waiting is the point: an
    acknowledgement means a daemon has decided to stop, not that it has finished
    tearing its warm context down.

    A daemon that will not go is reported rather than fatal -- see the module
    docstring for why that is survivable.
    """
    from partcad_client_utils import daemon

    running = daemon.live_daemon_dirs()
    if not running:
        return
    click.echo("Stopping %d running PartCAD daemon(s)..." % len(running))
    stopped = daemon.stop_all_daemons()
    left = len(running) - len(stopped)
    if left:
        click.echo(
            "Warning: %d PartCAD daemon(s) did not stop; they keep running the previous version "
            "until they are restarted." % left
        )


def _report_check(status: dict) -> None:
    """Print what `--check` found, without installing anything."""
    if status["reason"]:
        click.echo("PartCAD %s: %s." % (status["current"], status["reason"]))
    elif status["update_available"]:
        click.echo(
            "PartCAD %s is installed; %s is available (%s installation). "
            "Run `pc upgrade` to install it." % (status["current"], status["latest"], status["kind"])
        )
    else:
        click.echo("PartCAD %s is up to date." % status["current"])
