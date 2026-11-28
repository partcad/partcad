#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops deps list [OBJECT]`: what a package depends on, or what an object names.

The IDE's Dependencies tab (`ops.deps.list`). A package: the dependencies it
declares, each with the commit it is at and what its declaration says; the
packages its objects use without declaring them; and its sub-packages. An
object: what it names and places, with how and how many times. At a revision
(`//pkg@v1.2`) as at the working tree.
"""

import rich_click as click

from ....operations_args import (
    echo_json,
    print_object_dependencies,
    print_package_dependencies,
    run_subject,
    target_options,
)
from ....parameters import param_option, param_params


@click.command(
    help=(
        "List what the package -P selects depends on -- what it declares, what it uses without declaring it, its "
        "sub-packages -- or, with OBJECT, what OBJECT names and places, with how and how many times"
    )
)
@target_options
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
@param_option
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(cli_ctx, package, interface, assembly, scene, sketch, as_json, params, object):
    result = run_subject(
        cli_ctx, "ops.deps.list", (package, interface, assembly, scene, sketch, object), param_params(params)
    )
    if as_json:
        echo_json(result)
    elif result.get("object"):
        print_object_dependencies(result)
    else:
        print_package_dependencies(result)
