#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Core-side entry point for 'pc import assembly'.

An import reads a foreign file and leaves the package holding *PartCAD's own*
objects - parts it can render on their own and an ``.assy`` that places them -
rather than a declaration that points back at the foreign file. (Declaring one
is what ``pc add assembly`` is for.) Both supported formats work that way:

  * **STEP** - the file is split into one zeroed STEP part per solid and an
    ``.assy`` that places them.
  * **URDF** - each link becomes an ``stl`` part carrying the physical
    properties the URDF stated, each joint becomes a pair of interfaces, and
    the ``.assy`` connects the parts through them.

The STEP-CAF reader and every other OCCT operation an assembly import needs run
in a sandbox (see assembly_step_reader and wrappers/wrapper_import_assy.py), so
this module never touches a live OCP object: PartCAD does not depend on a CAD
library to import an assembly. Here we register the STEP parts the reader wrote
and turn the plain-data tree it returns into an .assy file.

This is the one-shot half of reading a STEP assembly: it materializes the parts
and the .assy file into the package, and from then on the package owns them. The
'step' assembly type (assembly_factory_step) is the other half - it reads the
very same file through the very same reader, but keeps everything in memory.
"""

import asyncio
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedSeq

from ... import logging as pc_logging
from ...assembly_step_reader import read_assembly_tree
from ...project import Project
from ..part import import_part_action


def import_urdf_action(project: Project, assembly_file: str, config: dict) -> str:
    """Import a URDF as the parts, interfaces and .assy that say the same thing.

    This is the same conversion ``pc convert assembly -t assy`` performs on a
    URDF assembly the package already declares, so it is done the same way: the
    URDF is registered as an assembly of the package for the length of the
    conversion and dropped again, leaving only what the conversion produced.
    Registering it in memory rather than writing it to 'partcad.yaml' first is
    what lets the source file live anywhere - the STEP import reads its file
    where it lies too.
    """
    from .convert import apply_config, urdf_to_assy

    name = Path(assembly_file).stem
    if project.get_assembly_config(name) is not None:
        raise ValueError(
            "The package already has an assembly named '%s'; rename the URDF file or remove it first" % name
        )

    urdf_config = {"type": "urdf", "path": str(Path(assembly_file).resolve())}
    # What the URDF reader takes from an assembly's declaration. An import has
    # nowhere to put them yet, but they arrive through 'config' when a caller
    # (the JSON-RPC service, a test) supplies them.
    for key in ("desc", "ignoreCollision", "packagePaths", "strict"):
        if config.get(key) is not None:
            urdf_config[key] = config[key]

    known = project.object_configs("assembly")
    known[name] = urdf_config
    try:
        sections = urdf_to_assy(project, name, urdf_config, Path(project.config_dir).resolve())
    finally:
        # Whatever happened, the package must not be left declaring a URDF
        # assembly that 'partcad.yaml' knows nothing about.
        known.pop(name, None)
        project.assemblies.pop(name, None)

    apply_config(project, sections)
    pc_logging.info(
        "Imported the URDF '%s' as %d parts and %d interfaces"
        % (name, len(sections["parts"]), len(sections["interfaces"]))
    )
    return name


def import_assy_action(
    project: Project,
    file_type: str,
    assembly_file: str,
    config: dict,
) -> str:
    """
    Imports an assembly into the project, supporting multiple file formats.

    Steps:
      1) A sandbox reads the assembly file, splits it into zeroed parts written
         as STEP files, and returns a hierarchical data tree.
      2) Each unique part is registered into the project.
      3) The tree is written out as an .assy file and added to the project.

    Supported formats:
      - STEP (.step, .stp)
      - URDF (.urdf), which takes the path through 'import_urdf_action'
    """
    config = config or {}

    file_path = Path(assembly_file)
    if not file_path.exists():
        raise FileNotFoundError(f"File '{assembly_file}' not found.")

    pc_logging.info(f"Starting import of assembly: {project.rel_path(assembly_file)} (Type: {file_type})")

    if file_type == "urdf":
        return import_urdf_action(project, assembly_file, config)

    assembly_name = Path(assembly_file).stem
    project_root = Path(project.config_dir).resolve()
    output_folder = project_root / assembly_name

    root = asyncio.run(
        read_assembly_tree(
            project.ctx,
            str(file_path.resolve()),
            str(output_folder),
            file_type=file_type,
            precision=5,
        )
    )

    # Register each unique part exactly once. The wrapper deduplicates by
    # geometry, so distinct nodes may point at the same STEP file; they share one
    # registered part and differ only by their location.
    registered: dict = {}

    def register(part_file: str) -> str:
        part_file = str(Path(part_file).resolve())
        if part_file in registered:
            return registered[part_file]
        name = Path(part_file).with_suffix("").relative_to(project_root).as_posix()
        import_part_action(project, "step", name, part_file, config)
        registered[part_file] = name
        return name

    def build(node):
        if node["type"] == "assembly":
            return {
                "type": "assembly",
                "name": node["name"],
                "links": [build(child) for child in node.get("links", [])],
            }
        location = CommentedSeq(node["location"])
        location.fa.set_flow_style()
        return {
            "type": "part",
            "name": node["name"],
            "part": register(node["part_file"]),
            "location": location,
        }

    top_data = build(root)
    assy_name = Path(top_data["name"]).name
    assy_file_path = output_folder / f"{assy_name}.assy"

    # Prepare .assy file data. When the STEP root is a single part rather than an
    # assembly, reference it as the sole link - otherwise the part is registered
    # but never linked and the .assy comes out empty, silently losing the import.
    assembly_data = {
        "name": top_data["name"].replace("\\", "/"),
        "description": config.get("desc", ""),
        "links": top_data["links"] if top_data["type"] == "assembly" else [top_data],
    }

    # Save assembly data to YAML format
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    with open(assy_file_path, "w", encoding="utf-8") as file:
        yaml.dump(assembly_data, file)

    # Add assembly to the project. Pass the absolute path: Project._validate_path
    # resolves a relative one against the *process* working directory, which is
    # not the package directory when the work runs in the detached daemon (cwd=/).
    # It relativizes the path to the package itself before storing it.
    project.add_assembly("assy", str(assy_file_path), config)

    pc_logging.info(f"Successfully created assembly file: {project.rel_path(assy_file_path)}")

    return assembly_data["name"]
