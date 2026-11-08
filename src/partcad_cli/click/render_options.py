#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The options `pc render` and `pc adhoc render` share, beyond the viewing angle.

`viewport.py` has the angle. What is here is the rest of what the two commands
have in common, so that a projection of a bare file is asked for in the same
words as a projection of an object a package declares:

* `--reproducible/--no-reproducible` -- which hidden-line algorithm draws the
  projection, for this run: the `reproducible:` key of a `render:` file type,
  passed for one command instead of written down, exactly as `--view` is its
  `viewport_origin`/`viewport_up`. Left unset, the file type's own setting
  stands. The two algorithms draw one geometry as different shapes and
  different numbers of them -- one arc where the other has several short ones,
  an arc where the other has a run of short lines -- which is why measuring a
  drawing means drawing it both ways (see the `gen-sketch` skill).

and, for `pc adhoc render` only, the `pc render` options that mean something
for a file with a throwaway package around it:

* `-t`/`--format` -- another spelling of `--output`, the file type to write;
* `-O`/`--output-dir` -- where to write it, when no output file is named;
* `-p`/`--param` -- a parameter of the file, for a script that reads one: it is
  declared in the throwaway package with the type its value is written in;
* `-e`/`--options-package` -- a package to read the file type from: one in the
  public index (`//pub/...`), which the throwaway package then imports, or a
  package directory on this machine. Which of the two is decided by the
  spelling alone: a name starting with `//` is a package, and is never looked
  for on disk -- so a directory is written without it (on Windows, a network
  share with backslashes).

`--turn` comes with the viewing angle (`viewport.py`), and `--style`, `--size`,
`--background` and `--quality` with the picture (`video.py`'s
`picture_options`).

The `pc render` options left out of `pc adhoc render` are the ones a single
file outside any package gives nothing to: `-P`, `-r`, `--fast-only`,
`--exclude` and a `...:` name (there is no package to walk), `-s`/`-i`/`-a`/
`-S` (the subcommand says what the file holds), `--with-ports`,
`--with-interfaces`, `--with-all`, `--port` and `--with-internals` (a file
outside a package has no ports or interfaces), `--filter` (a part or a sketch
has no links), `--ignore-manufacturability` (no instruction book is rendered
ad hoc) and a video's `--fps`, `--duration`, `--speed`, `--append` and
`--preset` (no video is rendered ad hoc).
"""

import os

import rich_click as click

from .parameters import param_option

REPRODUCIBLE_HELP = (
    "Draw the projection through the exact hidden-line algorithm (--reproducible) or the polygonal one "
    "(--no-reproducible) for this run: the 'reproducible' of a render file type in 'partcad.yaml'. "
    "Unset, the file type's own setting stands"
)


ADHOC_PARAM_HELP = (
    "Set a parameter of the file, as <name>=<value>, and repeat it for several: declared for it with the type "
    "its value is written in -- true or false, a whole number, a number, or text -- which is what a script reads"
)


def reproducible_option(command):
    """Add `--reproducible/--no-reproducible` to a command that writes a projection."""
    return click.option(
        "--reproducible/--no-reproducible",
        "reproducible",
        default=None,
        help=REPRODUCIBLE_HELP,
        show_envvar=True,
    )(command)


def reproducible_params(value):
    """The option as JSON-RPC params: nothing when it was not given, so the configuration stands."""
    return {} if value is None else {"reproducible": bool(value)}


def output_option(projections):
    """`--output`, `-t` or `--format`: the file type an ad-hoc render writes."""
    return click.option(
        "--output",
        "-t",
        "--format",
        "output_type",
        type=str,
        help=(
            "The file type to write: %s, or one the --options-package implements. "
            "Inferred from the output filename if not provided" % ", ".join(projections)
        ),
        show_envvar=True,
    )


_ADHOC_OPTIONS = (
    click.option(
        "-O",
        "--output-dir",
        help="Write the file into this directory, named after the input, when no output file is named",
        type=click.Path(exists=True, file_okay=False, dir_okay=True),
        show_envvar=True,
    ),
    click.option(
        "-e",
        "--options-package",
        help=(
            "Package to read the file type from: one in the public index ('//pub/...'), "
            "or the directory of a package on this machine, by its path. A name starting with '//' is always a package"
        ),
        type=str,
        show_envvar=True,
    ),
    lambda command: param_option(command, help=ADHOC_PARAM_HELP),
    reproducible_option,
)


def adhoc_options(command):
    """Add the `pc render` options that mean something ad hoc (see the module docstring)."""
    for decorator in reversed(_ADHOC_OPTIONS):
        command = decorator(command)
    return command


def adhoc_params(output_type, projections, output_dir, options_package, params, reproducible, output_filename):
    """The ad-hoc options as JSON-RPC params, checked as far as can be without the daemon.

    A file type no built-in projection writes is refused here unless a package
    to read it from is named, so that a typo costs a message rather than a round
    trip; with one, whether it declares the type is the daemon's to say. A
    directory is sent absolute, because the daemon runs elsewhere; a package
    name -- one starting with '//', which is what makes it one, there as here --
    is sent as written.
    """
    if output_type is not None and options_package is None and output_type not in projections:
        raise click.BadParameter(
            "'%s' is not a projection PartCAD writes: %s. A package that implements it is named with -e"
            % (output_type, ", ".join(projections)),
            param_hint="'--output'",
        )
    if output_dir is not None and output_filename is not None:
        raise click.UsageError("Name the output file or give --output-dir, not both")
    if options_package is not None and not options_package.startswith("//"):
        options_package = os.path.abspath(options_package)
    return {
        "output_type": output_type,
        "output_dir": os.path.abspath(output_dir) if output_dir else None,
        "options_package": options_package,
        "params": list(params or ()),
        **reproducible_params(reproducible),
    }
