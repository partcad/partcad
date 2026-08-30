#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Core-side entry point for 'pc import scene'.

An import reads a foreign file and leaves the package holding *PartCAD's own*
objects - parts it can render on their own and an ``.assy`` that places them -
rather than a declaration that points back at the foreign file. (Declaring one
is what ``pc add scene`` is for, and it is the right thing when the world file
is the source of truth and somebody else maintains it.)

One format is supported, and it is the one that describes an arrangement:

  * **Gazebo world** (``.world``, SDFormat) - every shape a model places
    becomes a part of the package, carrying whatever the world said about it,
    and the arrangement becomes an ``.assy`` scene that places them.

The world is read in a sandbox (see wrappers/wrapper_import_world.py), so this
module never touches a live OCP object.
"""

from pathlib import Path

from ... import logging as pc_logging
from ...project import Project


def import_world_action(project: Project, scene_file: str, config: dict) -> str:
    """Import a Gazebo world as the parts and .assy scene that say the same thing.

    This is the same conversion ``pc convert scene -t assy`` performs on a
    world scene the package already declares, so it is done the same way: the
    world is registered as a scene of the package for the length of the
    conversion and dropped again, leaving only what the conversion produced.
    Registering it in memory rather than writing it to 'partcad.yaml' first is
    what lets the source file live anywhere.
    """
    from ..assembly.convert import apply_config
    from .convert import world_to_assy

    name = Path(scene_file).stem
    if project.get_scene_config(name) is not None:
        raise ValueError(
            "The package already has a scene named '%s'; rename the world file or remove it first" % name
        )

    world_config = {"type": "world", "path": str(Path(scene_file).resolve())}
    # What the world reader takes from a scene's declaration. An import has
    # nowhere to put them yet, but they arrive through 'config' when a caller
    # (the JSON-RPC service, a test) supplies them.
    for key in ("desc", "ignoreCollision", "modelPaths"):
        if config.get(key) is not None:
            world_config[key] = config[key]

    known = project.object_configs("scene")
    known[name] = world_config
    try:
        sections = world_to_assy(project, name, world_config, Path(project.config_dir).resolve())
    finally:
        # Whatever happened, the package must not be left declaring a world
        # scene that 'partcad.yaml' knows nothing about.
        known.pop(name, None)
        project.scenes.pop(name, None)

    apply_config(project, sections)
    pc_logging.info("Imported the world '%s' as %d parts" % (name, len(sections["parts"])))
    return name


def import_scene_action(project: Project, file_type: str, scene_file: str, config: dict) -> str:
    """Import a scene from a file, dispatching on the file's format."""
    config = config or {}

    file_path = Path(scene_file)
    if not file_path.exists():
        raise FileNotFoundError("File '%s' not found." % scene_file)

    pc_logging.info("Starting import of scene: %s (Type: %s)" % (project.rel_path(scene_file), file_type))

    if file_type == "world":
        return import_world_action(project, scene_file, config)

    raise ValueError("Scenes are imported from 'world' files; '%s' is not one" % file_type)
