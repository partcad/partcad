#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`--fast-only`, shared by every command that walks packages for assemblies.

One definition, so that the flag reads the same in `pc render`, `pc test`,
`pc list` and the rest. What it leaves out is decided on the daemon, from the
declarations (see `partcad.fast_only` and `partcad_utils.timeouts`): every
assembly and scene that declares a `timeout:`, which is how a package says an
object is slow.

`-f` is its short name wherever that is free. `pc test` and `pc sim` have had
`-f` for `--filter` for a long time, and scripts say `pc test -f cad`, so there
the flag is `--fast-only` and nothing shorter.
"""

import rich_click as click

HELP = (
    "Leave out every assembly and scene that declares a 'timeout:' -- the ones its package says are slow. "
    "Meant for a recursive run over a large tree, such as CI"
)


def option(short: bool = True):
    """The `--fast-only` option, as `-f` too unless the command already uses it."""
    names = ("--fast-only", "-f") if short else ("--fast-only",)
    return click.option(*names, "fast_only", is_flag=True, default=False, show_envvar=True, help=HELP)
