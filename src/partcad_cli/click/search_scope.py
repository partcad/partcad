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
`partcad.actions.common`). `--each-package` asks every package its own search
all the same: slower, and what says which of a catalog's categories each hit
is in.
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


EACH_PACKAGE_HELP = (
    "Ask every package below its own search, even where a catalog's search at the top answers for the packages "
    "below it (searchScope: tree): a request per category, and each hit under the category it is in"
)


def each_package_option(command):
    """`--each-package` of a `pc search` command that finds shapes, off by default."""
    return click.option(
        "--each-package",
        "each_package",
        is_flag=True,
        default=False,
        show_envvar=True,
        help=EACH_PACKAGE_HELP,
    )(command)
