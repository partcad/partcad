import rich_click as click
from pprint import pformat
import partcad.logging as pc_logging


# TODO: https://stackoverflow.com/a/37491504/25671117
# TODO: @alexanderilyin: Replace -i, -a, -s, -S with --type
@click.command(help="Show detailed info on a part, assembly or scene")
@click.option(
    "-P",
    "--package",
    "package",
    type=str,
    help="Package to retrieve the object from",
    default=None,
)
@click.option("-i", "interface", is_flag=True, help="The object is an interface")
@click.option("-a", "assembly", is_flag=True, help="The object is an assembly")
@click.option("-s", "sketch", is_flag=True, help="The object is a sketch")
@click.option("-S", "scene", is_flag=True, help="The object is a scene")
@click.option(
    "-p",
    "--param",
    "params",
    type=str,
    multiple=True,
    metavar="<name>=<value>",
    help="Assign a value to the parameter",
)
@click.argument("object", type=str, required=False)  # help="Part (default), assembly or scene to show"
@click.pass_obj
def cli(ctx, package, interface, assembly, sketch, scene, object, params):  # , path
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
        pc_logging.info("CONFIGURATION: %s" % pformat(obj.config))
        info = obj.info()
        for k, v in info.items():
            pc_logging.info("INFO: %s: %s" % (k, pformat(v)))
