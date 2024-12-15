#
# OpenVMP, 2023-2024
#
# Author: Aleksandr Ilin (ailin@partcad.org)
# Created: Fri Nov 22 2024
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
import partcad.utils as pc_utils
import partcad.logging as logging
import asyncio

import partcad.logging as logging
import partcad.utils as pc_utils


async def cli_render_async(ctx, packages, output_dir, format, sketch, interface, assembly, object):
    tasks = []
    for package in packages:
        if not object is None:
            if not ":" in object:
                object = ":" + object
            package, object = pc_utils.resolve_resource_path(ctx.get_current_project_path(), object)

        if object is None:
            # Render all parts and assemblies configured to be auto-rendered in this project
            tasks.append(
                ctx.render_async(
                    project_path=package,
                    format=format,
                    output_dir=output_dir,
                )
            )
        else:
            # Render the requested part or assembly
            sketches = []
            interfaces = []
            parts = []
            assemblies = []
            if sketch:
                sketches.append(object)
            elif interface:
                interfaces.append(object)
            elif assembly:
                assemblies.append(object)
            else:
                parts.append(object)

            prj = ctx.get_project(package)
            if prj is None:
                logging.error("%s is not found" % package)
            else:
                tasks.append(
                    prj.render(
                        sketches=sketches,
                        interfaces=interfaces,
                        parts=parts,
                        assemblies=assemblies,
                        format=format,
                        output_dir=output_dir,
                    )
                )
    await asyncio.gather(*tasks)


# TODO: @alexanderilyin: Replace --scene, --interface, --assembly, --sketch with a single option --type
@click.command(help="Generate a rendered view of parts, assemblies, or scenes in the package")
@click.option(
    "-p",
    "--create-dirs",
    help="Create the necessary directory structure if it is missing",
    is_flag=True,
)
@click.option(
    "-O",
    "--output-dir",
    help="Create artifacts in the given output directory",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
)
@click.option(
    "-t",
    "--format",
    help="The type of file to export",
    type=click.Choice(
        [
            "readme",
            "svg",
            "png",
            "step",
            "stl",
            "3mf",
            "threejs",
            "obj",
            "gltf",
        ]
    ),
)
@click.option(
    "-P",
    "--package",
    help="Package to retrieve the object from",
    type=str,
)
@click.option(
    "-r",
    "--recursive",
    help="Recursively test all imported packages",
    is_flag=True,
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
@click.option(
    "-S",
    "--scene",
    help="The object is a scene",
    is_flag=True,
)
@click.argument("object", type=str, required=False)  # Part (default), assembly or scene to test
@click.pass_obj
def cli(ctx, create_dirs, output_dir, format, package, recursive, sketch, interface, assembly, scene, object):
    # with logging.Process("Render", "this"):
    #     ctx.option_create_dirs = create_dirs

    #     package = package if package is not None else ""
    #     if recursive:
    #         start_package = ctx.get_project_abs_path(package)
    #         all_packages = ctx.get_all_packages(start_package)
    #         packages = list(
    #             map(
    #                 lambda p: p["name"],
    #                 list(all_packages),
    #             )
    #         )
    #     else:
    #         packages = [package]

    #     asyncio.run(cli_render_async(ctx, packages, output_dir, format, sketch, interface, assembly, object))
    # DEBUG:root:Command error: Traceback (most recent call last):
    #   File "/workspaces/partcad/.venv/bin/partcad", line 6, in <module>
    #     sys.exit(cli())
    #   File "/workspaces/partcad/.venv/lib/python3.10/site-packages/rich_click/rich_command.py", line 367, in __call__
    #     return super().__call__(*args, **kwargs)
    #   File "/workspaces/partcad/.venv/lib/python3.10/site-packages/click/core.py", line 1157, in __call__
    #     return self.main(*args, **kwargs)
    #   File "/workspaces/partcad/.venv/lib/python3.10/site-packages/rich_click/rich_command.py", line 152, in main
    #     rv = self.invoke(ctx)
    #   File "/workspaces/partcad/.venv/lib/python3.10/site-packages/click/core.py", line 1688, in invoke
    #     return _process_result(sub_ctx.command.invoke(sub_ctx))
    #   File "/workspaces/partcad/.venv/lib/python3.10/site-packages/click/core.py", line 1434, in invoke
    #     return ctx.invoke(self.callback, **ctx.params)
    #   File "/workspaces/partcad/.venv/lib/python3.10/site-packages/click/core.py", line 783, in invoke
    #     return __callback(*args, **kwargs)
    #   File "/workspaces/partcad/.venv/lib/python3.10/site-packages/click/decorators.py", line 45, in new_func
    #     return f(get_current_context().obj, *args, **kwargs)
    #   File "<string>", line 155, in cli
    #   File "/usr/local/lib/python3.10/asyncio/runners.py", line 44, in run
    #     return loop.run_until_complete(main)
    #   File "/usr/local/lib/python3.10/asyncio/base_events.py", line 649, in run_until_complete
    #     return future.result()
    #   File "<string>", line 56, in cli_render_async
    #   File "/workspaces/partcad/partcad/src/partcad/project.py", line 1462, in render
    #     asyncio.run(self.render_async(sketches, interfaces, parts, assemblies, format, output_dir))
    #   File "/usr/local/lib/python3.10/asyncio/runners.py", line 33, in run
    #     raise RuntimeError(
    # RuntimeError: asyncio.run() cannot be called from a running event loop
    # sys:1: RuntimeWarning: coroutine 'Project.render_async' was never awaited
    # TODO: @alexanderilyin: Fix the error above
    with logging.Process("Render", "this"):
        ctx.option_create_dirs = create_dirs
        package = package if package is not None else ""
        if recursive:
            start_package = pc_utils.get_child_project_path(ctx.get_current_project_path(), package)
            all_packages = ctx.get_all_packages(start_package)
            packages = list(
                map(
                    lambda p: p["name"],
                    list(all_packages),
                )
            )
        else:
            packages = [package]

        for package in packages:
            if not object is None:
                if not ":" in object:
                    object = ":" + object
                # TODO: @clairbee: it seems that resolve_resource_path() does not resolve the resource path correctly for -p
                package, object = pc_utils.resolve_resource_path(ctx.get_current_project_path() + package, object)

            if object is None:
                # Render all parts and assemblies configured to be auto-rendered in this project
                ctx.render(
                    project_path=package,
                    format=format,
                    output_dir=output_dir,
                )
            else:
                # Render the requested part or assembly
                sketches = []
                interfaces = []
                parts = []
                assemblies = []
                if sketch:
                    sketches.append(object)
                elif interface:
                    interfaces.append(object)
                elif assembly:
                    assemblies.append(object)
                else:
                    parts.append(object)

                prj = ctx.get_project(package)
                prj.render(
                    sketches=sketches,
                    interfaces=interfaces,
                    parts=parts,
                    assemblies=assemblies,
                    format=format,
                    output_dir=output_dir,
                )
