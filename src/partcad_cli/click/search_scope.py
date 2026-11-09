#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`--recursive/--no-recursive`, shared by every `pc search` command.

A search reaches every package below the one it starts in unless told not to:
what is looked for is usually somewhere below, in a sub-package or in a package
that was imported, and a search that quietly looked at one package answered
"nothing" for things that were there. `-R` (`--no-recursive`) keeps it to the
one package; `-r` is still accepted, and `<package>...` still says the same as
it always did.

A package served by a repository plugin that searches a whole tree in one
request (its metadata says `searchScope: tree`) is asked once, at the top of
that tree, rather than once for every package in it (see `_search` in
`partcad.actions.common`).
"""

import rich_click as click

HELP = (
    "Search the package and every package below it, imported ones included (the default), or, with "
    "-R/--no-recursive, only the package itself"
)


def recursive_option(command):
    """The `-r/-R`, `--recursive/--no-recursive` option of a `pc search` command, on by default."""
    return click.option(
        "-r/-R",
        "--recursive/--no-recursive",
        "recursive",
        default=True,
        show_default=False,
        show_envvar=True,
        help=HELP,
    )(command)
