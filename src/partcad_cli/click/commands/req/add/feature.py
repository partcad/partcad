#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req add feature OBJECT NAME DESCRIPTION` -- a feature the object has to have, and a sentence saying what it is.

    pc req add feature bracket mount "Takes an M3 screw from either side"

Written as `requirements: features: <NAME>: <DESCRIPTION>`. A feature is prose:
`pc qual test` does not measure it, a simulation or an analysis scenario may
name it (`feature:`), and `/pc:validate` judges the rest.
"""

import rich_click as click

from .... import object_kind
from ....requirement_args import (
    add,
    object_options,
    object_params,
    read_stdin,
    refuse_both,
    replace_option,
    stdin_options,
)


@click.command(
    help="Require a feature of OBJECT: NAME, and DESCRIPTION, a sentence saying what it is. " + object_kind.LOOKED_UP
)
@object_options
@replace_option
@stdin_options
@click.argument("object", type=str)
@click.argument("name", type=str)
@click.argument("description", type=str, required=False)
@click.pass_obj
def cli(cli_ctx, package, assembly, scene, sketch, replace, from_stdin, as_json, object, name, description):
    refuse_both(from_stdin, {"DESCRIPTION": description})
    if from_stdin:
        value = read_stdin(as_json)
    elif description is None:
        raise click.UsageError("Say what the feature is: DESCRIPTION, or '--stdin'")
    else:
        value = description
    add(cli_ctx, object_params(package, assembly, scene, sketch, object), "feature", name, value, replace)
