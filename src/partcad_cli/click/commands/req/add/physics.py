#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req add physics OBJECT FIELD` -- a physical property the object has to have.

    pc req add physics bracket mass --value '>0,<=0.05'                # kg
    pc req add physics bracket centerOfMass --vector null null '<5'    # mm, one value per axis
    pc req add physics bracket inertia.ixx --value '>0'                # one member of a mapping

Written as `requirements: physics: <FIELD>:`. FIELD is any field of a
`physics:` section a shape states, in its units; a member of a mapping one is
`<field>.<member>`, or the whole mapping is given with `--stdin`.
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
    value,
)
from ....requirement_args import vector as typed_vector


@click.command(
    help=(
        "Require a physical property of OBJECT: FIELD ('mass', 'centerOfMass', 'inertia.ixx', ...), in the units "
        "a 'physics:' section states it in. " + object_kind.LOOKED_UP
    )
)
@object_options
@replace_option
@stdin_options
@click.option("--value", "required", type=str, default=None, help="The value: a number, or comparisons ('>0,<=1')")
@click.option(
    "--vector",
    nargs=3,
    type=str,
    default=None,
    metavar="X Y Z",
    help="The value of a vector, one per axis: each a number or comparisons, 'null' for none",
)
@click.argument("object", type=str)
@click.argument("field", type=str)
@click.pass_obj
def cli(cli_ctx, package, assembly, scene, sketch, replace, from_stdin, as_json, required, vector, object, field):
    refuse_both(from_stdin, {"--value": required, "--vector": vector})
    if required is not None and vector:
        raise click.UsageError("'--value' and '--vector' both say what it is: use one")
    if from_stdin:
        written = read_stdin(as_json)
    elif vector:
        written = typed_vector(vector)
    elif required is not None:
        written = value(required)
    else:
        raise click.UsageError("Say what '%s' is required to be: '--value', '--vector' or '--stdin'" % field)
    add(cli_ctx, object_params(package, assembly, scene, sketch, object), "physics", field, written, replace)
