from pathlib import Path
import shutil
import tempfile
from typing import Optional
import partcad.logging as pc_logging
from partcad.project import Project
from partcad.adhoc.convert import convert_cad_file
from .add import add_part_action

def import_part_action(project: Project, kind: str, name: str, source_path: str,
                       config: Optional[dict] = None, target_format: Optional[str] = None):
    """Import an existing part into the project, optionally converting it first using ad-hoc conversion."""
    config = config or {}
    source_path = Path(source_path).resolve()
    original_source = source_path

    pc_logging.info(f"Importing '{name}' ({kind}) from '{source_path}'")

    if not source_path.exists():
        raise ValueError(f"Source file '{source_path}' not found.")

    # Ad-hoc conversion
    if target_format and target_format != kind:
        temp_dir = Path(tempfile.mkdtemp())
        converted_path = temp_dir / f"{name}.{target_format}"

        pc_logging.info(f"Performing ad-hoc conversion: {kind} -> {target_format}")
        convert_cad_file(str(source_path), kind, str(converted_path), target_format)

        if not converted_path.exists():
            raise RuntimeError(f"Ad-hoc conversion failed: {source_path} -> {converted_path}")

        kind, source_path = target_format, converted_path
        pc_logging.info(f"Ad-hoc conversion successful: {converted_path}")

    # Copy file into project
    target_path = (Path(project.path) / f"{name}.{kind}").resolve()
    if not target_path.exists() or not source_path.samefile(target_path):
        try:
            shutil.copy2(source_path, target_path)
        except shutil.Error as e:
            raise ValueError(f"Failed to copy '{source_path}' -> '{target_path}': {e}")

    add_part_action(project, kind, str(target_path), config)
    pc_logging.info(f"Part '{name}' imported successfully.")

    # Cleanup temporary files
    if source_path != original_source:
        shutil.rmtree(temp_dir, ignore_errors=True)
