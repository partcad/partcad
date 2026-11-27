#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops used-by [OBJECT]`: what uses an object, or a package.

The IDE's Operations > Used By tab (`ops.used_by`): every object the daemon has
loaded that refers to OBJECT, with how and how many times -- and, for a package
(no OBJECT, or one written as `//pkg`), the packages that declare it as a
dependency, each with the revision it pins and how far behind that is. A
package at a revision (`//pkg@v1.2`) is what uses it at that revision. Only what
is loaded is looked at, which the command says when it finds nothing; `--load`
loads every package of the workspace first.
"""

import rich_click as click

from ...operations_args import echo_json, print_used_by, run_subject, subject_of, target_options
from ...parameters import param_option, param_params


@click.command(
    help=(
        "List what uses OBJECT -- or, with no OBJECT, the package -P selects: the packages that declare it as a "
        "dependency, and the objects PartCAD has loaded that use it, each with how and how many times. --load "
        "loads every package of the workspace first."
    )
)
@target_options
@click.option("--load", is_flag=True, help="Load every package below the root first, so that all of them are asked")
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
@param_option
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(cli_ctx, package, interface, assembly, scene, sketch, load, as_json, params, object):
    result = run_subject(
        cli_ctx,
        "ops.used_by",
        (package, interface, assembly, scene, sketch, object),
        {"load": load, **param_params(params)},
    )
    if as_json:
        echo_json(result)
    else:
        print_used_by(result, subject_of(result))
