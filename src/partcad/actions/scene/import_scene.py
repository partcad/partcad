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

Any format that describes an arrangement is supported, which is whatever the
package graph declares under 'import:' with 'scene' among its 'kinds' - a Gazebo
world (``.world``, SDFormat) and an MJCF model today, both from a plugin package.
Every shape a model places becomes a part of the package, carrying whatever the
file said about it, and the arrangement becomes an ``.assy`` scene that places
them.

The file is read in a sandbox by the reader that format's declaration names, so
this module never touches a live OCP object and never knows which format it was.
"""

from pathlib import Path

from ... import logging as pc_logging
from ...project import Project

# What a scene's declaration can carry through to its reader. An import has
# nowhere to put them yet, but they arrive through 'config' when a caller (the
# JSON-RPC service, a test) supplies them. Deliberately a short list of the
# options readers share rather than "whatever was passed": a key a reader has
# never heard of is a typo, and writing it into the declaration hides it.
READER_OPTIONS = ("desc", "ignoreCollision", "modelPaths", "packagePaths")


def import_scene_file_action(project: Project, file_type: str, scene_file: str, config: dict) -> str:
    """Import an arrangement file as the parts and .assy scene that say the same.

    This is the same conversion ``pc convert scene -t assy`` performs on a scene
    the package already declares, so it is done the same way: the file is
    registered as a scene of the package for the length of the conversion and
    dropped again, leaving only what the conversion produced. Registering it in
    memory rather than writing it to 'partcad.yaml' first is what lets the source
    file live anywhere.
    """
    from ..assembly.convert import apply_config
    from .convert import file_to_assy

    name = Path(scene_file).stem
    if project.get_scene_config(name) is not None:
        raise ValueError("The package already has a scene named '%s'; rename the file or remove it first" % name)

    scene_config = {"type": file_type, "path": str(Path(scene_file).resolve())}
    for key in READER_OPTIONS:
        if config.get(key) is not None:
            scene_config[key] = config[key]

    known = project.object_configs("scene")
    known[name] = scene_config
    try:
        sections = file_to_assy(project, name, scene_config, Path(project.config_dir).resolve())
    finally:
        # Whatever happened, the package must not be left declaring a scene that
        # 'partcad.yaml' knows nothing about.
        known.pop(name, None)
        project.scenes.pop(name, None)

    apply_config(project, sections)
    pc_logging.info("Imported '%s' as %d parts" % (name, len(sections["parts"])))
    return name


# The name this had while a Gazebo world was the only thing it could read.
import_world_action = import_scene_file_action


def import_scene_action(project: Project, file_type: str, scene_file: str, config: dict) -> str:
    """Import a scene from a file of any format the graph reads as a scene."""
    from .convert import ASSY, scene_format

    config = config or {}

    file_path = Path(scene_file)
    if not file_path.exists():
        raise FileNotFoundError("File '%s' not found." % scene_file)

    if file_type == ASSY:
        raise ValueError(
            "'%s' is PartCAD's own scene format, so there is nothing to import from it: "
            "declare it with 'pc add scene' instead." % ASSY
        )
    # Raises where the graph does not read this format as a scene, and says
    # which of the two things is wrong.
    scene_format(project, file_type, "source")

    pc_logging.info("Starting import of scene: %s (Type: %s)" % (project.rel_path(scene_file), file_type))
    return import_scene_file_action(project, file_type, scene_file, config)
