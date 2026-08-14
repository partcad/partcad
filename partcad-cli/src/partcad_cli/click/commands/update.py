#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""`pc update` -- bring PartCAD and everything it imports up to date.

Two things go stale and both are updated here: the PartCAD installation itself
(the Python wheels, or the standalone bundle that carries its own interpreter)
and the packages the current package imports. The installation goes first, so a
package that needs a newer PartCAD gets one.

The self-update half runs **in the client process**, which is the exception to
the command boundary and the only place it can run. Updating an installation is
a client-side act: it is this machine's copy of PartCAD being replaced, by the
process running from it. A daemon must not do it -- a daemon can be remote,
where "update PartCAD" would mean updating somebody else's installation.

This command owns the one piece of daemon handling the update needs: its own
workspace's daemon runs from the files about to be replaced, so it is asked to
stop and waited for -- but only once a newer version has been found, so a no-op
`pc update` never costs anybody their warm context. It stops *its* daemon and no
others: hunting for other workspaces' daemons would race every other client on
the machine, and is unnecessary, because the new version is installed beside the
old one rather than over it. A daemon left running keeps serving from intact
files until it is restarted.

The package half stays a thin daemon call, as it has always been.
"""

import rich_click as click
from partcad_utils import selfupdate

from ..service import run


@click.command(help="Update PartCAD itself and all imported packages to their latest versions.")
@click.option(
    "--partcad-only",
    is_flag=True,
    help="Update PartCAD itself, and leave the imported packages alone.",
)
@click.option(
    "--packages-only",
    is_flag=True,
    help="Update the imported packages, and leave PartCAD itself alone.",
)
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
@click.pass_obj
def cli(cli_ctx, partcad_only: bool, packages_only: bool, check: bool, to_version: str) -> None:
    if partcad_only and packages_only:
        raise click.UsageError("--partcad-only and --packages-only are mutually exclusive")
    if packages_only and (check or to_version):
        raise click.UsageError("--packages-only cannot be combined with --check or --to-version")

    updated = False
    if not packages_only:
        # Failing to update PartCAD itself is fatal only when that was the whole
        # request. Otherwise it is reported and the packages are still updated: a
        # source checkout, or an index that cannot be reached, is no reason for
        # `pc update` to stop doing the thing it has always done.
        updated = _update_partcad(check, to_version, fatal=partcad_only or check)
        if check:
            return

    if not partcad_only:
        if updated:
            # This process is still the version it started as, and so is the
            # daemon it is about to start: the launcher it runs lives in the
            # installation that was just superseded. Saying so beats a `pc
            # version` that disagrees with the line printed a second ago.
            click.echo("Updating the imported packages with the previous PartCAD; the new one runs from now on.")
        run(cli_ctx, "update", span_name="update", needs_context=True)


def _update_partcad(check_only: bool, to_version: str, fatal: bool) -> bool:
    """Check, and unless asked only to check, install a newer PartCAD.

    Returns True when something was actually installed.
    """
    from partcad_utils.user_config import user_config

    if user_config.offline:
        # `--offline` is a promise that nothing is fetched, and looking a release
        # up is a fetch. The packages half honors it on the daemon side.
        click.echo("Offline mode: skipping the PartCAD version check.")
        return False

    try:
        if check_only:
            _report_check(selfupdate.check(to_version=to_version))
            return False
        # `update` narrates itself through the log callback: what it found and
        # where the new version landed. `before_install` runs in between, once
        # something newer is confirmed and before anything is written.
        result = selfupdate.update(to_version=to_version, log=click.echo, before_install=_stop_workspace_daemon)
        return bool(result.get("updated"))
    except selfupdate.SelfUpdateError as e:
        if fatal:
            raise click.ClickException(str(e))
        click.echo("PartCAD itself was not updated: %s. Continuing with the imported packages." % e)
        return False


def _stop_workspace_daemon() -> None:
    """Stop this workspace's daemon and wait for it to actually be gone.

    Run just before the new version is written, because the daemon is executing
    the files that are about to be replaced. Waiting is the point: an
    acknowledgement means the daemon has decided to stop, not that it has
    finished tearing its warm context down.
    """
    from partcad_service_json_rpc import daemon

    if daemon.stop_daemon(wait=daemon.STOP_TIMEOUT):
        click.echo("Stopped the PartCAD daemon for this workspace.")


def _report_check(status: dict) -> None:
    """Print what `--check` found, without installing anything."""
    if status["reason"]:
        click.echo("PartCAD %s: %s." % (status["current"], status["reason"]))
    elif status["update_available"]:
        click.echo(
            "PartCAD %s is installed; %s is available (%s installation). "
            "Run `pc update` to install it." % (status["current"], status["latest"], status["kind"])
        )
    else:
        click.echo("PartCAD %s is up to date." % status["current"])
