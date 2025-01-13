import partcad.logging as logging
import partcad.utils as pc_utils
import rich_click as click


@click.command(help="Regenerate a sketch, part or assembly")
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
@click.argument(
    "object", type=str, required=False
)  # help="Path to the part (default), assembly or scene to regenerate"
@click.pass_obj
def cli(ctx, sketch, interface, assembly, scene, package, object):
    if sketch or interface or assembly or scene:
        object_type = "sketch" if sketch else "interface" if interface else "assembly" if assembly else "scene"
        logging.error(
            f"Regeneration of {object_type} objects is not yet supported. " "Currently, only parts can be regenerated."
        )
        return

    if not ":" in object:
        object = ":" + object
    package, object = pc_utils.resolve_resource_path(ctx.get_current_project_path(), object)

    package = ctx.get_project(package)
    obj = package.get_part(object)
    obj.regenerate()
