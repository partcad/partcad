#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ..service import run


@click.command(help="Produce the route files of the objects that declare a 'cam:' section")
@click.option(
    "-P",
    "--package",
    help="Package to retrieve the object from",
    type=str,
    show_envvar=True,
)
@click.option(
    "-i",
    "--implementation",
    help=(
        "Who produces the route, as '<package>:<file type>'. Overrides the default "
        "for this run only; the default itself is the 'camImplementation' user "
        "configuration option, and an object may name one in its own 'cam:' section"
    ),
    type=str,
    show_envvar=True,
)
@click.option(
    "-O",
    "--output-dir",
    help="Write the route files into the given directory instead of where the configuration puts them",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    show_envvar=True,
)
@click.option(
    "-p",
    "--create-dirs",
    help="Create the necessary directory structure if it is missing",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-r",
    "--recursive",
    help="Produce the routes of all imported packages too",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-s",
    "--sketch",
    help="The object is a sketch",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "--json",
    "as_json",
    help="Print what was produced as the JSON array it is, instead of as a report",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-m",
    "--machine",
    help="Which of the machines an object names to write for: 'cnc', 'laser' or 'drill'. "
    "Needed only by an object that names more than one, since they are alternatives",
    type=str,
    show_envvar=True,
)
@click.argument("object", type=str, required=False)  # The object to route; all of them by default
@click.pass_obj
def cli(cli_ctx, package, implementation, output_dir, create_dirs, recursive, sketch, as_json, machine, object):
    """Produce the program a machine cuts these objects with.

    With no object named this is a *package-level* command, which is what
    separates it from `pc cae fea`: an analysis is asked of one part, while a
    route is what a package's cut list is made of, and the objects that have one
    are exactly the objects whose `manufacturing:` section says something about
    being cut. Everything else in the package is passed over without a word.

    An object may name several machines. They are *alternatives* -- ways it
    could be made, not stages it goes through -- so one of them is chosen per
    run with `--machine`, and a part that really is machined in stages is a
    chain of parts each naming the previous one as its `source`.

    The report is printed by the daemon through PartCAD logging, exactly as
    `pc cae` prints its findings, so that what a user sees does not depend on
    which client asked. `--json` is the exception: a machine-readable array has
    to reach stdout of *this* process to be piped anywhere.
    """
    result = run(
        cli_ctx,
        "cam.route",
        {
            "package": package,
            "object": object,
            "implementation": implementation,
            # Resolved to absolute so the routes land in the user's working
            # directory rather than the daemon's, which is somewhere else.
            "output_dir": os.path.abspath(output_dir) if output_dir else None,
            "create_dirs": create_dirs,
            "recursive": recursive,
            "sketch": sketch,
            "machine": machine,
            "json": as_json,
        },
        needs_context=True,
    )
    if as_json:
        import json

        click.echo(json.dumps((result or {}).get("routes") or [], indent=2))

    # Printed first, then failed. An object whose section is wrong must not cost
    # the other nineteen their record: the files are on disk either way, and a
    # caller piping `--json` has as much use for the routes that were produced
    # as for the news that one was not. The daemon has already reported each
    # failure against the object it belongs to.
    failed = (result or {}).get("failed") or []
    if failed:
        raise click.ClickException("No route was produced for %s" % ", ".join(failed))
