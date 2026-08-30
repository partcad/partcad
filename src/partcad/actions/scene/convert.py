#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Core-side entry point for 'pc convert scene'.

Converts a scene between the two formats that can express one:

  * **to world** - the scene is exported as a Gazebo ``.world`` file
    (SDFormat) plus a directory of the mesh files it references, and the
    package's declaration switches to ``type: world``.

  * **to assy** - every shape the world places becomes a part of the package
    and the arrangement becomes an ``.assy`` that places them, so the package
    ends up holding PartCAD's own objects. The declaration switches to
    ``type: assy``.

This is the scene counterpart of 'pc convert assembly', and it is deliberately
the simpler of the two. Converting a URDF assembly to ASSY has to reconcile two
different models of *connection* - a URDF joint against a pair of PartCAD ports
- because an assembly says how it is put together. A scene says only where
things are, and SDFormat's poses are placements just as an ASSY's ``location:``
is, so nothing has to be invented in either direction: what a world's joints
say is what a scene does not carry in the first place (see
'scene_factory_world').
"""

import asyncio
import shutil
from pathlib import Path

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from ... import logging as pc_logging
from ...project import Project
from ...utils import resolve_resource_path
from ..assembly.convert import _location, _section, _yaml, apply_config

SUPPORTED_FORMATS = ("assy", "world")


def _relative_to_package(project: Project, path: Path) -> str:
    """A path as the package's configuration should carry it."""
    try:
        return str(path.resolve().relative_to(Path(project.config_dir).resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _safe_stem(name: str) -> str:
    """A node name as a file name: the '/' that groups it is not a directory."""
    return str(name).replace("/", "_").replace("\\", "_") or "shape"


def world_to_assy(project: Project, scene_name: str, config: dict, out_dir: Path):
    """Turn a world scene into an ASSY one, with parts of the package's own.

    Every shape the world places is copied into ``<scene>/`` inside the package
    and declared as a part of the format it already is - the file is copied
    rather than re-rendered, so no geometry is re-triangulated and what a mesh
    said stays exactly what it said. What the world stated about a link (its
    mass, its friction, its colour) travels with the part, in the same
    ``properties:`` section every other PartCAD object carries it in.

    The arrangement itself becomes an ``.assy`` whose nesting is the world's:
    one node per model, holding one link per shape, each placed by the pose the
    world gave it.
    """
    scene = project.get_scene(scene_name)
    if scene is None:
        raise ValueError("Scene '%s' not found in '%s'" % (scene_name, project.name))
    factory = getattr(scene, "world_factory", None)
    if factory is None:
        raise ValueError("Scene '%s' is not a world scene" % scene_name)

    result = asyncio.run(factory.read_async())
    root = result["root"]

    parts = CommentedMap()
    copied: dict = {}

    def part_entry(node):
        """Declare the part one shape node becomes, copying its file in."""
        part_name = "%s/%s" % (scene_name, node["name"])
        if part_name in parts:
            return part_name

        source = Path(node["part_file"])
        relative = "%s/%s%s" % (scene_name, _safe_stem(node["name"]), source.suffix)
        target = out_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # One copy per source file: a world that repeats a shape (a row of
        # pallets, a bolt) should not fill the package with identical meshes.
        already = copied.get(str(source.resolve()))
        if already is None:
            shutil.copyfile(source, target)
            copied[str(source.resolve())] = relative
        else:
            relative = already

        entry = CommentedMap()
        entry["type"] = node["part_type"]
        entry["path"] = relative
        entry["desc"] = "Link '%s' of the scene '%s'" % (node.get("link") or node["name"], scene_name)
        scale = float(node.get("scale") or 1.0)
        if abs(scale - 1.0) > 1e-9:
            entry["scale"] = scale
        properties = CommentedMap()
        for key in ("material", "color"):
            if node.get(key):
                properties[key] = node[key]
        physics = _section(node.get("physics"))
        if physics:
            properties["physics"] = physics
        if properties:
            entry["properties"] = properties
        parts[part_name] = entry
        return part_name

    def build(node):
        entry = CommentedMap()
        if node["type"] == "assembly":
            entry["name"] = Path(node["name"]).name
            if node.get("location"):
                entry["location"] = _location(node["location"])
            entry["links"] = CommentedSeq([build(child) for child in node.get("links") or []])
            return entry
        entry["part"] = ":%s" % part_entry(node)
        entry["name"] = Path(node["name"]).name
        if node.get("location"):
            entry["location"] = _location(node["location"])
        return entry

    links = CommentedSeq([build(child) for child in root.get("links") or []])
    # Geometry the world defines but does not place - the visual shapes of a
    # link built from its collision geometry, and the other way round. They are
    # declared as parts, exactly as the world scene registers them, and are as
    # absent from the arrangement here as they were there.
    for node in root.get("parts") or []:
        part_entry(node)

    if not parts:
        raise ValueError("The world scene '%s' has no geometry to convert" % scene_name)

    assy_path = out_dir / ("%s.assy" % scene_name)
    document = CommentedMap()
    document["name"] = scene_name
    if result.get("world_name"):
        document["description"] = "Converted from the Gazebo world '%s'" % result["world_name"]
    document["links"] = links
    with open(assy_path, "w", encoding="utf-8") as f:
        _yaml().dump(document, f)

    scene_config = CommentedMap({"type": "assy"})
    if config.get("desc"):
        scene_config["desc"] = config["desc"]
    scene_config["path"] = _relative_to_package(project, assy_path)

    return {"scenes": {scene_name: scene_config}, "parts": parts}


def assy_to_world(project: Project, scene_name: str, config: dict, out_dir: Path):
    """Export a scene as a Gazebo world file plus the mesh files it references."""
    scene = project.get_scene(scene_name)
    if scene is None:
        raise ValueError("Scene '%s' not found in '%s'" % (scene_name, project.name))

    world_path = out_dir / ("%s.world" % scene_name)
    world_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(scene.render_async(project.ctx, "world", project=project, filepath=str(world_path)))
    if not world_path.exists():
        raise RuntimeError("Failed to write the world file for '%s'" % scene_name)

    scene_config = CommentedMap({"type": "world"})
    if config.get("desc"):
        scene_config["desc"] = config["desc"]
    scene_config["path"] = _relative_to_package(project, world_path)

    return {"scenes": {scene_name: scene_config}}


def convert_scene_action(
    project: Project,
    object_name: str,
    target_format: str = None,
    output_dir: str = None,
    dry_run: bool = False,
):
    """Convert a scene to another format and update its declaration."""
    if target_format not in SUPPORTED_FORMATS:
        raise ValueError(
            "Scenes convert between %s; '%s' is not one of them"
            % (" and ".join(sorted(SUPPORTED_FORMATS)), target_format)
        )

    package_name, scene_name = resolve_resource_path(project.name, object_name)
    if package_name != project.name:
        project = project.ctx.get_project(package_name)
        if project is None:
            raise ValueError("Package '%s' not found for '%s'" % (package_name, scene_name))

    config = project.get_scene_config(scene_name)
    if config is None:
        raise ValueError("Scene '%s' not found in '%s'" % (scene_name, project.name))
    source_format = config.get("type")
    if source_format == target_format:
        pc_logging.info("Scene '%s' is already '%s'; nothing to convert." % (scene_name, target_format))
        return None
    if source_format not in SUPPORTED_FORMATS:
        raise ValueError("Scenes of type '%s' cannot be converted" % source_format)

    out_dir = Path(output_dir).resolve() if output_dir else Path(project.config_dir).resolve()
    if dry_run:
        pc_logging.info(
            "[Dry Run] Would convert the scene '%s' from '%s' to '%s' in %s"
            % (scene_name, source_format, target_format, out_dir)
        )
        return None

    pc_logging.info("Converting the scene '%s': %s to %s (%s)" % (scene_name, source_format, target_format, out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)

    if target_format == "world":
        sections = assy_to_world(project, scene_name, config, out_dir)
    else:
        sections = world_to_assy(project, scene_name, config, out_dir)

    apply_config(project, sections)
    pc_logging.info("Conversion of the scene '%s' is completed." % scene_name)
    return sections
