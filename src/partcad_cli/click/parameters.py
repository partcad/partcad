#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'-p'/'--param', shared by every command that names an object.

An object with particular parameter values is named by them: 'bolt;length=10'
is the bolt ten long, and every command that takes an object takes that name.
This is the same request spelled one value at a time -- 'pc render bolt -p
length=10' -- which needs none of the quoting a ';' needs in a shell.

What it means is the daemon's: the values travel as 'params', a list of
'<name>=<value>', and 'operations._assigned_name' writes them into the name of
the object the request names, so that a log line, a file name and a cache entry
all say which instance they are about. A value given here wins over one the name
already carries. Each one is read here as well, by the same
'partcad_utils.parameters.assignments' the daemon reads them with, so that a
value with no '=' in it costs a message rather than a round trip.

'-p' is free on every command that takes this. It is '--path' on 'pc' itself,
'--private' on 'pc init' and '--provider' on 'pc supply', none of which names an
object; 'pc render -P <package> bolt -p length=10' is '--package' and
'--param'.
"""

import rich_click as click

from partcad_utils import parameters

HELP = (
    "Set a parameter of the object, as <name>=<value>, and repeat it for several. "
    "The same as naming the object '<object>;<name>=<value>,...', with no ';' to quote"
)


def _check(ctx, param, value):
    for item in value or ():
        try:
            parameters.assignments([item])
        except ValueError as e:
            raise click.BadParameter(str(e), ctx=ctx, param=param) from e
    return value


def param_option(command):
    """Add '-p'/'--param' to a command."""
    return click.option(
        "-p",
        "--param",
        "params",
        type=str,
        multiple=True,
        metavar="<name>=<value>",
        callback=_check,
        help=HELP,
        show_envvar=True,
    )(command)


def param_params(params):
    """The option as JSON-RPC params, so every caller sends the same name."""
    return {"params": list(params or ())}
