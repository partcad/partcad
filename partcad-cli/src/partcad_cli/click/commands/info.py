import rich_click as click
from pprint import pformat
import partcad.logging as logging


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
    is_flag=True, help="The object is a scene",
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
def cli(ctx, package, interface, assembly, sketch, scene, object, params):  # , path
    param_dict = {}
    if params is not None:
        for kv in params:
            k, v = kv.split("=")
            param_dict[k] = v

    if package is None:
        path = object if ":" in object else ":" + object
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
            logging.error(f"Object {object} not found")
        else:
            logging.error(f"Object {object} not found in package {package}")
    else:
        logging.info(f"CONFIGURATION: {pformat(obj.config)}")
        info = obj.info()
        for k, v in info.items():
            logging.info(f"INFO: {k}: {pformat(v)}")
