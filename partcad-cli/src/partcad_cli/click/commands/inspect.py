import rich_click as click  # import click

#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-23
#
# Licensed under Apache License, Version 2.0.
#

import partcad.logging as pc_logging


# TODO: @clairbee: fix type checking here
# TODO: @alexanderilyin: https://stackoverflow.com/a/37491504/25671117
@click.command(help="Visualize a part, assembly or scene")
@click.option(
    "-V",
    "--verbal",
    "verbal",
    is_flag=True,
    help="Produce a verbal output instead of a visual one",
)
@click.option(
    "-P",
    "--package",
    "package",
    type=str,
    help="Package to retrieve the object from",
    default=None,
)
@click.option(
    "-s",
    "--sketch",
    help="The object is a sketch",
    is_flag=True,
)
@click.option(
    "-i",
    "--interface",
    help="The object is an interface",
    is_flag=True,
)
@click.option(
    "-a",
    "--assembly",
    help="The object is an assembly",
    is_flag=True,
)
# @click.option(
#     "-S",
#     "--scene",
#     help="The object is a scene",
#     is_flag=True,
# )
@click.option(
    "-p",
    "--param",
    "params",
    metavar="<param_name>=<param_value>",
    help="Assign a value to the parameter",
)
@click.argument("object", type=str, required=False)  # help="Part (default), assembly or scene to test"
@click.pass_context
@click.pass_obj
def cli(ctx, context, verbal, package, interface, assembly, sketch, params, object):
    params = {}
    if not params is None:
        for kv in params:
            k, v = kv.split("=")
            params[k] = v

    if package is None:
        if ":" in object:
            path = object
        else:
            path = ":" + object
    else:
        path = package + ":" + object

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
            pc_logging.error("Object %s not found" % object)
        else:
            pc_logging.error("Object %s not found in package %s" % (object, package))
    else:
        if verbal:
            if package is None:
                package_obj = ctx.get_project("/")
            else:
                package_obj = ctx.get_project(package)

            summary = obj.get_summary(package_obj)
            pc_logging.info("Summary: %s" % summary)
            # TODO: @alexanderilyin: Test with dedicated test scenario
            if not context.parent.params.get("q"):
                print("%s" % summary)
        else:
            obj.show()
