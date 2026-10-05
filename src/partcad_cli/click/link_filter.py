#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The ``<filter-file|filter-expression>`` argument, shared by the three commands
that take one.

``pc filter`` takes it as its first argument, and ``pc render``/``pc export``
take it as ``--filter``; it means the same thing in all three -- which links of
an assembly or a scene to keep -- and the rules for reading one are written down
once, in `partcad_utils.assy_filter`.

**The argument is resolved here, in the client, and the daemon is sent the mask
rather than the text.** That is not an optimisation: the argument is a filename
first, and the file is on the machine the user typed the command on. A daemon
may be on another machine, where the path names nothing -- or, worse, names
something else. So the one side that can open the file is the side that opens
it, exactly as `pc lint --file` reads the file it checks (see "Command boundary"
in ``src/partcad_cli/AGENTS.md``); what crosses the wire is a small mapping of
names.

A failure here is a `click.BadParameter`, so a mistyped filename costs a message
and not a round trip. Which of the two failures it was -- there is no such file,
or there is and it does not parse -- is in the message, because the two are
fixed in different places.
"""

import rich_click as click

# What the argument is called wherever it travels: the CLI option, the JSON-RPC
# parameter, and the IDE's own request. One spelling, so a client cannot send a
# name the daemon does not read.
PARAM = "filter"

HELP = (
    "Keep only some of the links of the assembly or scene: a JSON or YAML file naming them, "
    "or the same written out on the command line. "
    "A link named with nothing under it keeps everything inside it; a link named with children "
    "under it keeps those children only"
)


def resolve(ctx, param, value):
    """Read a filter argument into the mask it names, for click to hand on."""
    if value is None:
        return None

    # Deferred: 'pc --help' imports every command module to print its short
    # help, and this pulls in a YAML parser.
    from partcad_utils import assy_filter

    try:
        data, source = assy_filter.resolve_spec(value)
        # Parsed here as well as resolved, so that a malformed mask is refused
        # by the command the user typed rather than by the daemon it reached.
        assy_filter.parse(data, "the filter from %s" % source)
    except assy_filter.FilterError as e:
        raise click.BadParameter(str(e), ctx=ctx, param=param) from e
    return data


def filter_option(command):
    """Add ``--filter`` to a command.

    No short form. ``-f`` is ``--fast-only`` on both commands that take this
    one, and Click resolves a repeated short flag by letting the last one
    registered win -- so claiming it here turned ``pc render -f widget`` into a
    filter of 'widget' with no object named, silently, where it used to be a
    fast-only render of 'widget'. ``fast_only.option(short=False)`` is how a
    command that owns ``-f`` for something else says so (``pc test``, ``pc
    sim``), and neither of these two does.
    """
    return click.option(
        "--filter",
        "link_filter",
        help=HELP,
        type=str,
        callback=resolve,
        show_envvar=True,
    )(command)


def filter_params(link_filter) -> dict:
    """The resolved mask as JSON-RPC params, so every caller sends one name."""
    return {PARAM: link_filter}
