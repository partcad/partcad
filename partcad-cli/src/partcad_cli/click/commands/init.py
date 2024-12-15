#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko, Aleksandr Ilin
# Created: 2023-12-23
#
# Licensed under Apache License, Version 2.0.
#
import rich_click as click
import os
import partcad.logging as logging
from partcad.globals import create_package


@click.command(help="Create a new PartCAD package in the current directory")
# TODO: All long options everywhere
@click.option("-p", is_flag=True, help="Initialize this package as private")
@click.pass_context
def cli(ctx: click.rich_context.RichContext, p):
    # TODO: @alexanderilyin: Deal with noise like "PartCAD configuration file is not found"
    logging.had_errors = False
    if not ctx.parent.params.get("p") is None:
        if os.path.isdir(ctx.parent.params.get("p")):
            # TODO: Move filename to constant somewhere.
            dst_path = os.path.join(ctx.parent.params.get("p"), "partcad.yaml")
        else:
            dst_path = ctx.parent.params.get("p")
    else:
        dst_path = "partcad.yaml"

    if not create_package(dst_path, p):
        logging.error("Failed creating '%s'!" % dst_path)
