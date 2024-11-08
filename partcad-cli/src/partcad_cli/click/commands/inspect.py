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
@click.command(help="* Visualize a part, assembly or scene")
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
    "-i", "interface", is_flag=True, help="The object is an interface"
)
@click.option("-a", "assembly", is_flag=True, help="The object is an assembly")
@click.option("-s", "sketch", is_flag=True, help="The object is a sketch")
# @click.option("-S", "scene", is_flag=True, help="The object is a scene")
@click.option(
    "--object",
    "object",
    type=str,
    help="Path to the part (default), assembly or scene to inspect",
)
@click.option(
    "-p",
    "--param",
    "params",
    metavar="<param_name>=<param_value>",
    help="Assign a value to the parameter",
)
@click.pass_obj
def cli(ctx, verbal, package, interface, assembly, sketch, object, params):
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
            pc_logging.error(
                "Object %s not found in package %s" % (object, package)
            )
    else:
        if verbal:
            if package is None:
                package_obj = ctx.get_project("/")
            else:
                package_obj = ctx.get_project(package)

            summary = obj.get_summary(package_obj)
            pc_logging.info("Summary: %s" % summary)
            # TODO: @alexanderilyin: Test this manually
            if not ctx.parent.params.get("q"):
                print("%s" % summary)
        else:
            obj.show()
