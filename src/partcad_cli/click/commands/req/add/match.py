#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req add match OBJECT OTHER` -- how closely the object's volume, displacement or mass has to match another's.

    pc req add match bracket :bracket-v1 --mass 5 --volume 10%

Written as `requirements: match: <OTHER>: <amount>: <percent>`, each amount
on its own: one given here is added beside those required already. OTHER is
found from OBJECT's package, as `pc compare` finds it, before anything is
written. `--weight` is `--mass`, and is written as `mass`.
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

PERCENT = "How many percent of OTHER's it may differ by, either way: '5' or '5%'"


@click.command(
    help=(
        "Require OBJECT's volume, displacement or mass to be within some percent of OTHER's. " + object_kind.LOOKED_UP
    )
)
@object_options
@replace_option
@stdin_options
@click.option("--volume", type=str, default=None, help="Its volume: " + PERCENT)
@click.option(
    "--displacement",
    type=str,
    default=None,
    help="Its displacement (its volume and every void sealed in it): " + PERCENT,
)
@click.option("--mass", "--weight", "mass", type=str, default=None, help="Its mass: " + PERCENT)
@click.argument("object", type=str)
@click.argument("other", type=str)
@click.pass_obj
def cli(
    cli_ctx, package, assembly, scene, sketch, replace, from_stdin, as_json, volume, displacement, mass, object, other
):
    amounts = {"volume": volume, "displacement": displacement, "mass": mass}
    refuse_both(from_stdin, {"--%s" % key: given for key, given in amounts.items()})
    if from_stdin:
        limits = read_stdin(as_json)
    else:
        limits = {key: value(given) for key, given in amounts.items() if given is not None}
        if not limits:
            raise click.UsageError("Say how closely: '--volume', '--displacement', '--mass' or '--stdin'")
    add(cli_ctx, object_params(package, assembly, scene, sketch, object), "match", other, limits, replace)
