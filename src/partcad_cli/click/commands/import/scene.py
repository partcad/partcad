#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os
from pathlib import Path

import rich_click as click

from ...service import run

# What a file extension says the format is, where the caller does not say.
#
# 'scene_type: [file_extensions]', and empty, because PartCAD implements no
# scene *file* format of its own: 'assy' is its own way of saying where things
# are and is not imported into itself, and every other arrangement format
# belongs to a simulation engine's plugin package ('sim-gazebo:world',
# 'sim-mujoco:mjcf'). A guess made here could only name a type that no longer
# resolves, which is worse than asking.
#
# It stays as a table rather than becoming a removed feature: a package that
# teaches PartCAD an arrangement format can be named with '-t', and if PartCAD
# ever implements one itself this is where its extensions go. Everything below
# already treats an unclaimed extension as "say it with -t" rather than as an
# error, so an empty table needs no other change.
SUPPORTED_SCENE_FORMATS_WITH_EXT = {}


@click.command(help="Import a scene from a file, creating parts and an ASSY (Assembly YAML).")
@click.argument("scene_file", type=str, required=True)
@click.option(
    "-t",
    "--type",
    "scene_type",
    type=str,
    default=None,
    help="The format the file is in, where the extension does not say or says the wrong thing. "
    "A format a package reads as a scene, named through it: 'sim-gazebo:world', 'sim-mujoco:mjcf'.",
)
@click.option("--desc", type=str, help="Optional description for the imported scene.")
@click.option(
    "-P",
    "--package",
    help="Package to import the object to",
    type=str,
    default=".",
)
@click.pass_obj
def cli(cli_ctx, package: str, scene_file: str, scene_type: str, desc: str):
    """
    CLI command to import a scene from a file.
    Automatically creates multiple parts and a scene.

    A Gazebo world becomes one part per shape its models place, plus an ASSY
    scene that places them. The package ends up holding PartCAD's own objects -
    `pc add scene` is what declares a file where it lies instead.

    Served by the daemon: the read runs in the sandboxed reader the format's own
    `import:` declaration names, whose Python runtime belongs to the daemon. Which
    formats those are is a fact about the workspace's packages, so an unknown one
    is the daemon's to report and not this command's to rule out.
    """
    file_path = Path(scene_file)
    if not file_path.exists():
        raise click.UsageError(f"File '{scene_file}' not found.")

    if not scene_type:
        detected_ext = file_path.suffix.lstrip(".").lower()
        for supported_type, extensions in SUPPORTED_SCENE_FORMATS_WITH_EXT.items():
            if detected_ext in extensions:
                scene_type = supported_type

    if not scene_type:
        # The tail is only worth printing when there is something in it; with
        # nothing recognised by extension, "Recognised by extension: ." is noise
        # in front of the sentence that actually says what to do.
        recognised = ", ".join(sorted(SUPPORTED_SCENE_FORMATS_WITH_EXT))
        raise click.ClickException(
            f"Cannot tell from its name what format '{scene_file}' is in. "
            f"Name it with '-t' -- a format a package reads as a scene, such as 'sim-gazebo:world' "
            f"(from the package that implements it, which this workspace has to import)."
            + (f" Recognised by extension: {recognised}." if recognised else "")
        )

    params = {
        "obj_kind": "scene",
        # Absolute: the daemon does not share the client's working directory.
        "source": os.path.abspath(scene_file),
        "scene_type": scene_type,
        "package": package,
    }
    if desc:
        params["desc"] = desc

    result = run(cli_ctx, "import.object", params, span_name="import scene", needs_context=True)
    click.echo(f"Scene '{(result or {}).get('name', file_path.stem)}' imported successfully.")
