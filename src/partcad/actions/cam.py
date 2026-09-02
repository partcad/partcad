#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc cam': the manufacturing instructions for one part.

Unlike 'pc export' and 'pc render', which write a file wherever they are told
and are done, this produces the file **twice over**, and on purpose:

  * once in the package, next to the part it is for. That copy is the package's
    own - it is what the part is made from, it belongs with the part, and it is
    written once and left alone afterwards. A second run finds it and does not
    rebuild it, which is what makes the instructions a thing a repository can
    hold rather than something regenerated under everyone who asks.
  * once where the user is standing, under whatever name they asked for. That
    copy is the answer to the command, and it is a copy: the machine gets fed
    from it, and feeding a machine is not something to do to a file in a
    repository.

Which file type is produced is the package's business too - a plugin declares
it, with the extension it writes - so this never names one.
"""

import os
import shutil

from .. import logging as pc_logging
from .. import output
from ..exception import NotManufacturableError
from ..part import Part


def cam_formats(ctx, shape, project=None, options_project=None) -> list:
    """The 'cam:' file types declared for this object."""
    return shape.cam_formats(ctx, project=project, options_project=options_project)


def resolve_format(ctx, shape, format_name=None, project=None, options_project=None) -> str:
    """Which file type to produce, or a refusal that says what the choice is.

    A package that declares one is what the common case looks like, and naming
    it on every command line would be noise. A package that declares several is
    a package that has to be asked which.
    """
    declared = cam_formats(ctx, shape, project=project, options_project=options_project)
    if format_name:
        if declared and format_name not in declared:
            raise ValueError(
                "'%s' is not one of the manufacturing instructions %s:%s declares (%s)"
                % (format_name, shape.project_name, shape.name, ", ".join(declared))
            )
        return format_name
    if not declared:
        raise ValueError(
            "Neither %s:%s nor its package declares a 'cam:' file type."
            " Import a package that implements one - see the '%s' section in the documentation."
            % (shape.project_name, shape.name, output.CAM)
        )
    if len(declared) > 1:
        raise ValueError(
            "%s:%s has more than one kind of manufacturing instructions; name one with '-t' (%s)"
            % (shape.project_name, shape.name, ", ".join(declared))
        )
    return declared[0]


def cam_info(ctx, shape, project=None, options_project=None) -> dict:
    """What kinds of instructions this object has, and which can be drawn.

    Cheap on purpose - it reads configuration and builds nothing - because it is
    what an editor asks before deciding whether to offer a CAM view at all.

    'visual' is the file type the implementation's picture is written as, and is
    None when the implementation offers no picture. Only the first file type is
    consulted for it where a package declares several: an editor showing one CAM
    view has one to show.
    """
    if project is None:
        project = ctx.get_project(shape.project_name)
    formats = cam_formats(ctx, shape, project=project, options_project=options_project)
    info = {"formats": formats, "visual": None, "format": None}
    if not formats:
        return info

    for format_name in formats:
        impl, _ = shape.output_getopts(
            ctx, format_name, project, filepath=None, options_project=options_project, output_dir=None
        )
        if impl.supports_visual:
            info["format"] = format_name
            info["visual"] = impl.visual_extension
            return info
    info["format"] = formats[0]
    return info


async def visual_model_async(ctx, shape, format_name=None, project=None, options_package=None, **kwargs) -> bytes:
    """The plugin's picture of the instructions, as binary glTF.

    Two steps, and the second is the one worth explaining. The plugin writes the
    model in whatever it finds natural - a tool path is a shape, and STL says
    that as well as anything - and an editor draws glTF. So what the plugin wrote
    is converted, by the very exporter 'pc export -t gltf' uses, in the sandbox
    it runs in. Nothing here knows what the plugin chose to write.
    """
    import asyncio
    import tempfile

    from ..adhoc.adhoc import write_output_file

    with tempfile.TemporaryDirectory() as directory:
        model = await cam_async(
            ctx,
            shape,
            format_name=format_name,
            project=project,
            options_package=options_package,
            visual=True,
            output_dir=directory,
            ignore_manufacturability=True,
            **kwargs,
        )
        gltf = os.path.join(directory, "visual.glb")
        # Binary, so that what comes back is one file: a text glTF carries its
        # buffers beside it, and there is nothing to carry them in.
        #
        # On a thread of its own because the ad-hoc machinery builds a context
        # and drives it with 'asyncio.run()', which is an error on a thread that
        # already has a loop running - and this is called from one.
        await asyncio.to_thread(
            write_output_file,
            model,
            os.path.splitext(model)[1].lstrip(".").lower(),
            gltf,
            "gltf",
            kind="part",
            verb="Visualize",
            binary=True,
        )
        with open(gltf, "rb") as f:
            return f.read()


async def cam_async(
    ctx,
    shape,
    format_name=None,
    project=None,
    options_package=None,
    visual: bool = False,
    output_dir=None,
    output_name=None,
    force: bool = False,
    ignore_manufacturability: bool = False,
    **kwargs,
) -> str:
    """Produce the instructions for 'shape' and hand back the path of the copy.

    'output_dir' is where that copy goes, defaulting to the working directory,
    and 'output_name' is what it is called, defaulting to the name the package's
    own copy has. 'force' rewrites the package's copy, which is otherwise
    produced once and then left alone.
    """
    if not isinstance(shape, Part):
        raise ValueError(
            "%s:%s is not a part. Manufacturing instructions are written for a part;"
            " an assembly is put together out of parts that each have their own." % (shape.project_name, shape.name)
        )
    if not ignore_manufacturability and not shape.is_manufacturable:
        raise NotManufacturableError(
            "%s:%s is not manufacturable: pass --ignore-manufacturability to produce the instructions anyway"
            % (shape.project_name, shape.name)
        )

    if project is None:
        project = ctx.get_project(shape.project_name)
    options_project = ctx.get_project(options_package) if options_package else None
    if options_package and options_project is None:
        raise ValueError("The options package is not found: %s" % options_package)

    format_name = resolve_format(ctx, shape, format_name, project, options_project)

    # Where the package keeps it. The package's own configuration decides -
    # 'prefix' and 'extension' mean here what they mean for every other output
    # file - and the package directory is what a relative one is relative to.
    impl, package_path = shape.output_getopts(
        ctx,
        format_name,
        project,
        filepath=None,
        options_project=options_project,
        output_dir=getattr(project, "config_dir", None),
        visual=visual,
    )
    if visual and not impl.supports_visual:
        raise ValueError(
            "The '%s' implementation draws nothing: it declares no 'visual' file type for %s:%s"
            % (format_name, shape.project_name, shape.name)
        )
    package_path = os.path.abspath(package_path)

    if force or not os.path.exists(package_path):
        ctx.ensure_dirs_for_file(package_path)
        await shape.cam_async(
            ctx,
            format_name,
            project=project,
            filepath=package_path,
            options_package=options_package,
            visual=visual,
            **kwargs,
        )
        if not os.path.exists(package_path):
            raise Exception(
                "The '%s' implementation reported success but wrote nothing: %s" % (format_name, package_path)
            )
    else:
        pc_logging.info("Reusing the instructions the package already has: %s" % package_path)

    return _copy_out(package_path, output_dir, output_name)


def _copy_out(package_path, output_dir, output_name) -> str:
    """Put a copy of the package's file where the command was run.

    A copy of the same file under the same name is not one: the command was run
    in the package directory, and there is nothing to copy it to.
    """
    directory = os.path.abspath(output_dir or os.getcwd())
    name = output_name or os.path.basename(package_path)
    # A name with a directory in it is allowed and means what it says, so that
    # '-o build/part.gcode' works; it is still resolved against the output
    # directory rather than escaping to an absolute path of its own.
    target = name if os.path.isabs(name) else os.path.join(directory, name)
    target = os.path.abspath(target)

    if target == package_path:
        return package_path

    parent = os.path.dirname(target)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    shutil.copyfile(package_path, target)
    return target
