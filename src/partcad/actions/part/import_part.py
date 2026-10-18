#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from ... import logging as pc_logging
from ...adhoc.convert import convert_cad_file
from ...project import Project
from .add import add_part_action


def gltf_companions(source_path: Path) -> list:
    """The files a '.gltf' file names beside itself: its buffers and its images.

    A '.glb' carries them inside, and a URI that is a 'data:' URL or a web
    address is not a file to copy; anything else is a path relative to the
    '.gltf', and the part cannot be read without it.
    """
    try:
        with open(source_path, encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, UnicodeDecodeError, ValueError):
        return []  # a '.glb' under the '.gltf' name, or not glTF at all
    found = []
    for section in ("buffers", "images"):
        for item in document.get(section) or []:
            uri = item.get("uri") if isinstance(item, dict) else None
            # Only what sits at or below the '.gltf': a copy must land inside
            # the package it is imported into.
            if not uri or ":" in uri or uri.startswith(("/", "\\")) or ".." in Path(uri).parts:
                continue
            companion = (source_path.parent / uri).resolve()
            if companion.is_file():
                found.append(uri)
    return found


def import_part_action(
    project: Project,
    kind: str,
    name: str,
    source_path: str,
    config: Optional[dict] = None,
    target_format: Optional[str] = None,
):
    """Import an existing part into the project, optionally converting it first using ad-hoc conversion."""
    config = config or {}
    source_path = Path(source_path).resolve()
    original_source = source_path

    pc_logging.info(f"Importing '{name}' ({kind}) from '{project.rel_path(source_path)}'")

    if not source_path.exists():
        raise ValueError(f"Source file '{source_path}' not found.")

    # If a target format is specified, perform ad-hoc conversion before adding to project
    if target_format and target_format != kind:
        temp_dir = Path(tempfile.mkdtemp())
        converted_path = temp_dir / f"{name}.{target_format}"

        pc_logging.info(f"Performing ad-hoc conversion: {kind} -> {target_format}")
        convert_cad_file(str(source_path), kind, str(converted_path), target_format)

        if not converted_path.exists():
            raise RuntimeError(f"Ad-hoc conversion failed: {source_path} -> {converted_path}")

        kind, source_path = target_format, converted_path
        pc_logging.info(f"Ad-hoc conversion successful: {converted_path}")

    target_path = (Path(project.path) / f"{name}.{kind}").resolve()
    if not target_path.exists() or not source_path.samefile(target_path):
        try:
            shutil.copy2(source_path, target_path)
        except shutil.Error as e:
            raise ValueError(f"Failed to copy '{source_path}' -> '{target_path}': {e}")
        if kind == "gltf":
            for uri in gltf_companions(source_path):
                companion_target = (target_path.parent / uri).resolve()
                companion_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path.parent / uri, companion_target)

    add_part_action(project, kind, str(target_path), config)
    pc_logging.info(f"Part '{name}' imported successfully.")

    # Cleanup temporary files if ad-hoc conversion was performed
    if source_path != original_source:
        try:
            shutil.rmtree(temp_dir)
            pc_logging.info(f"Cleaned up temporary conversion directory: {temp_dir}")
        except Exception as e:
            pc_logging.warning(f"Failed to remove temp directory '{temp_dir}': {e}")
