#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ..service import run


# TODO-98: @clairbee: fix type checking here
# TODO: @alexanderilyin: https://stackoverflow.com/a/37491504/25671117
@click.command(help="View a part, assembly, or scene visually")
@click.option(
    "-V",
    "--verbal",
    "verbal",
    is_flag=True,
    help="Produce a verbal output instead of a visual one",
    show_envvar=True,
)
@click.option(
    "-P",
    "--package",
    "package",
    type=str,
    help="Package to retrieve the object from",
    default=None,
    show_envvar=True,
)
@click.option(
    "-s",
    "--sketch",
    help="The object is a sketch",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-i",
    "--interface",
    help="The object is an interface",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-a",
    "--assembly",
    help="The object is an assembly",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-S",
    "--scene",
    help="The object is a scene",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-p",
    "--param",
    "params",
    multiple=True,
    metavar="<param_name>=<param_value>",
    help="Assign a value to the parameter",
    show_envvar=True,
)
@click.argument("object", type=str, required=False)  # help="Part (default), assembly or scene to test"
@click.pass_context
@click.pass_obj
def cli(cli_ctx, context, verbal, package, interface, assembly, sketch, scene, params, object):
    rpc_params = {
        "verbal": verbal,
        "interface": interface,
        "assembly": assembly,
        "sketch": sketch,
        "scene": scene,
        "params": list(params),
        "object": object,
    }
    if package is not None:
        rpc_params["package"] = package

    result = run(cli_ctx, "inspect.object", rpc_params, span_name="inspect", needs_context=True)

    # TODO-99: @alexanderilyin: Test with dedicated test scenario
    if verbal and result and result.get("summary") is not None:
        if not context.parent.params.get("q"):
            print("%s" % result["summary"])
