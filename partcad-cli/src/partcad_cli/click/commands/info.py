#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
from pprint import pformat

import partcad as pc
from ..cli_context import CliContext


# TODO-94: @alexanderilyin: Replace -i, -a, -s, -S with --type; https://stackoverflow.com/a/37491504/25671117
@click.command(help="Show detailed information about a part, assembly, or scene")
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
    "-i",
    "--interface",
    "interface",
    is_flag=True,
    help="The object is an interface",
    show_envvar=True,
)
@click.option(
    "-a",
    "--assembly",
    "assembly",
    is_flag=True,
    help="The object is an assembly",
    show_envvar=True,
)
@click.option(
    "-s",
    "--sketch",
    "sketch",
    is_flag=True,
    help="The object is a sketch",
    show_envvar=True,
)
@click.option(
    "-S",
    "--scene",
    "scene",
    is_flag=True,
    help="The object is a scene",
    show_envvar=True,
)
@click.option(
    "-p",
    "--param",
    "params",
    type=str,
    multiple=True,
    metavar="<name>=<value>",
    help="Assign a value to the parameter",
    show_envvar=True,
)
@click.argument("object", type=str, required=False)  # help="Part (default), assembly or scene to show"
@click.pass_obj
def cli(cli_ctx: CliContext, package, interface, assembly, sketch, scene, object, params):  # , path
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        param_dict = {}
        if params is not None:
            for kv in params:
                k, v = kv.split("=")
                param_dict[k] = v

        if package is None:
            path = object if ":" in object else ":" + object
        else:
            path = package + ":" + object

        obj: pc.Shape
        if assembly:
            obj = ctx.get_assembly(path, params=params)
        elif interface:
            obj = ctx.get_interface(path)
        elif sketch:
            obj = ctx.get_sketch(path, params=params)
        else:
            obj = ctx.get_part(path, params=params)

        if obj is None:
            if package is None:
                pc.logging.error(f"Object {object} not found")
            else:
                pc.logging.error(f"Object {object} not found in package {package}")
        else:
            # TODO: call normalize config method for updating the parameters
            pc.logging.info(f"CONFIGURATION: {pformat(obj.config)}")
            info = obj.info()
            for k, v in info.items():
                pc.logging.info(f"INFO: {k}: {pformat(v)}")
