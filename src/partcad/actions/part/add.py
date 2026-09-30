#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

from pathlib import Path
from typing import Optional

import partcad.logging as pc_logging
from partcad.project import Project


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
