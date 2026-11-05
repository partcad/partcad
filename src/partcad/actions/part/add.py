#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

from pathlib import Path
from typing import Optional, Tuple

import partcad.logging as pc_logging
from partcad.project import Project
from partcad_utils.part_kinds import FILE_PART_FACTORIES


def addable_part_kinds(ctx) -> Tuple[str, ...]:
    """The part types a part can be added from a file as: what 'pc add part' takes.

    PartCAD's own file-reading factories, then the native CAD formats it ships
    as 'partTypes' in '//builtin/import', in the order that package declares
    them. The client spells the second half from 'partcad_client.object_types'
    instead, and 'tests/partcad/unit/test_add.py' holds the two to each other
    (see 'partcad_utils.part_kinds').
    """
    from partcad.output import IMPORT, builtin_project

    project = builtin_project(ctx, IMPORT)
    declared = (project.config_obj.get("partTypes") or {}) if project is not None else {}
    return FILE_PART_FACTORIES + tuple(name for name in declared if name not in FILE_PART_FACTORIES)


def add_part_action(project: Project, kind: str, path: str, config: Optional[dict] = None) -> bool:
    """Add an existing part to the project without copying. True if it was added."""
    config = config or {}
    path = Path(path)
    name = path.stem

    pc_logging.info(f"Adding part '{name}' ({kind}) from '{project.rel_path(path)}'")

    with pc_logging.Process("AddPart", project.name):
        result = project.add_part(kind, str(path), config)
        if result:
            pc_logging.info(f"Part '{name}' added successfully.")
    return bool(result)
