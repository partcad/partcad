#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os
from pathlib import Path

import rich_click as click

from ...service import run

# scene_type: [file_extensions]. '.sdf' is accepted beside '.world' because a
# Gazebo model is written in the same format and a world often is too; what is
# read is the same SDFormat document either way.
SUPPORTED_SCENE_FORMATS_WITH_EXT = {
    "world": ["world", "sdf"],
}


@click.command(help="Import a scene from a file, creating parts and an ASSY (Assembly YAML).")
@click.argument("scene_file", type=str, required=True)
@click.option("--desc", type=str, help="Optional description for the imported scene.")
@click.option(
    "-P",
    "--package",
    help="Package to import the object to",
    type=str,
    default=".",
)
@click.pass_obj
def cli(cli_ctx, package: str, scene_file: str, desc: str):
    """
    CLI command to import a scene from a file.
    Automatically creates multiple parts and a scene.

    A Gazebo world becomes one part per shape its models place, plus an ASSY
    scene that places them. The package ends up holding PartCAD's own objects -
    `pc add scene` is what declares a file where it lies instead.

    Served by the daemon: the read runs in a sandboxed wrapper
    (`wrapper_import_world`), whose Python runtime belongs to the daemon.
    """
    file_path = Path(scene_file)
    if not file_path.exists():
        raise click.UsageError(f"File '{scene_file}' not found.")

    scene_type = None
    detected_ext = file_path.suffix.lstrip(".").lower()
    for supported_type in SUPPORTED_SCENE_FORMATS_WITH_EXT.keys():
        if detected_ext in SUPPORTED_SCENE_FORMATS_WITH_EXT[supported_type]:
            scene_type = supported_type

    if not scene_type:
        raise click.ClickException(
            f"Cannot determine file type for '{scene_file}'. "
            f"Supported scene types: {', '.join(set(SUPPORTED_SCENE_FORMATS_WITH_EXT.keys()))}. "
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
