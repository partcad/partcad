#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'-x'/'--exclude', shared by every command that walks a subtree of packages.

A walk is written as a package with '...' on the end (or '-r'), and this is how
it leaves part of that subtree out: '-x //pub/universe/lego/ldraw' keeps the
twenty thousand parts the LDraw library serves out of a test of '//pub...'
without giving up the rest of it. Every command offers the same spelling for
the same reason the viewport options are shared: one walk, one way to narrow
it.

What it means is the daemon's: 'Context.get_all_packages' does not import an
excluded package or anything below it, and does not list one that something
else has loaded anyway. Naming a package here does not make it unreachable -
an assembly can still use a part from it - only absent from the walk.
"""

import rich_click as click

_OPTION = click.option(
    "--exclude",
    "-x",
    multiple=True,
    metavar="PACKAGE",
    show_envvar=True,
    help=(
        "Leave this package and everything below it out of a walk over a subtree "
        "('<package>...' or '-r'). Repeat it to leave out more than one"
    ),
)


def exclude_option(command):
    """Add '-x'/'--exclude' to a command."""
    return _OPTION(command)


def exclude_params(exclude):
    """The option as JSON-RPC params, so every caller sends the same name."""
    return {"exclude": list(exclude or ())}
