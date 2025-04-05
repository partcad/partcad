#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
from ..cli_context import CliContext


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
def cli(cli_ctx: CliContext, context, verbal, package, interface, assembly, sketch, scene, params, object):
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        package = ctx.resolve_package_path(package)
        package_obj: pc.Project = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return
        package = package_obj.name  # '//' may end up having a different name

        with pc.logging.Process("inspect", package):
            param_dict = {}
            if params is not None:
                for kv in params:
                    k, v = kv.split("=")
                    param_dict[k] = v

            package, object = pc.utils.resolve_resource_path(ctx.get_current_project_path(), object)
            path = f"{package}:{object}"

            if assembly:
                obj = ctx.get_assembly(path, params=param_dict)
            elif interface:
                obj = ctx.get_interface(path)
            elif sketch:
                obj = ctx.get_sketch(path, params=param_dict)
            else:
                obj = ctx.get_part(path, params=param_dict)

            if obj is None:
                pc.logging.error(f"Object {path} is not found")
            else:
                if verbal:
                    summary = obj.get_summary(package_obj)
                    pc.logging.info("Summary: %s" % summary)
                    # TODO-99: @alexanderilyin: Test with dedicated test scenario
                    if not context.parent.params.get("q"):
                        print("%s" % summary)
                else:
                    obj.show(ctx)
