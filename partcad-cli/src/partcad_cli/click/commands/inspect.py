import rich_click as click
import partcad.logging as logging


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
def cli(ctx, context, verbal, package, interface, assembly, sketch, scene, params, object):
    with logging.Process("inspect", "this"):
        param_dict = {}
        if params is not None:
            for kv in params:
                k, v = kv.split("=")
                param_dict[k] = v

        if package is None:
            if ":" in object:
                path = object
            else:
                path = ":" + object
        else:
            path = package + ":" + object

        if assembly:
            obj = ctx.get_assembly(path, params=param_dict)
        elif interface:
            obj = ctx.get_interface(path)
        elif sketch:
            obj = ctx.get_sketch(path, params=param_dict)
        else:
            obj = ctx.get_part(path, params=param_dict)

        if obj is None:
            if package is None:
                logging.error("Object %s not found" % object)
            else:
                logging.error("Object %s not found in package %s" % (object, package))
        else:
            if verbal:
                if package is None:
                    package_obj = ctx.get_project("/")
                else:
                    package_obj = ctx.get_project(package)

                summary = obj.get_summary(package_obj)
                logging.info("Summary: %s" % summary)
                # TODO-99: @alexanderilyin: Test with dedicated test scenario
                if not context.parent.params.get("q"):
                    print("%s" % summary)
            else:
                obj.show(ctx)
