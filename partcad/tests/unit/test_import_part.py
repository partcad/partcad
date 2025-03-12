import os
import shutil
from unittest.mock import patch
import pytest
import yaml
from pathlib import Path
from partcad.context import Context
from partcad import Project
from partcad.actions.part import import_part_action

# Mapping file extensions to formats
EXTENSION_MAPPING = {
    "step": "step",
    "brep": "brep",
    "stl": "stl",
    "3mf": "3mf",
    "threejs": "json",
    "obj": "obj",
    "gltf": "gltf",
}

# Supported formats
SUPPORTED_FORMATS = list(EXTENSION_MAPPING.keys())

# Source directory with real test files
SOURCE_DIR = Path("/workspaces/partcad/examples/feature_convert")

# Test parts (real files must exist in SOURCE_DIR)
PARTS_CONFIG = {
    "box_brep": {"type": "brep", "path": "brep/box.brep"},
    "cube_3mf": {"type": "3mf", "path": "3mf/cube.3mf"},
    "cube_stl": {"type": "stl", "path": "stl/cube.stl"},
    "bolt_step": {"type": "step", "path": "step/bolt.step"},
}


@pytest.mark.parametrize("source_part", PARTS_CONFIG.keys())
def test_import_real_part(source_part: str, tmp_path: Path):
    """
    Test importing a real part file into a new project.
    """
    source_config = PARTS_CONFIG[source_part]
    part_type = source_config["type"]
    source_file = Path(source_config["path"])

    real_source_path = SOURCE_DIR / source_file
    if not real_source_path.exists():
        pytest.skip(f"Real source file {real_source_path} not found.")

    # Set up test project
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    source_path = project_dir / source_file
    source_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(real_source_path, source_path)

    # Create empty configuration
    config_data = {"parts": {}}
    yaml_path = project_dir / "partcad.yaml"
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")

    # Import part
    import_part_action(project, part_type, source_part, str(source_path))

    # Reload config after import
    ctx = Context(str(project_dir))
    project = ctx.get_project("")
    updated_config = project.get_part_config(source_part)

    # Ensure part was registered in configuration
    assert updated_config is not None, f"Part {source_part} was not added to the project config."

    # Ensure the imported file exists in the project directory
    expected_path = Path(project.path) / f"{source_part}.{part_type}"
    assert expected_path.exists(), f"Expected imported file {expected_path} does not exist."


def test_import_missing_source_file(tmp_path: Path):
    """
    Test handling of a missing source file during import.
    """
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    ctx = Context(str(project_dir))
    project = ctx.get_project("")

    with pytest.raises(ValueError, match="Source file .* not found."):
        import_part_action(project, "step", "missing_part", str(tmp_path / "missing_file.step"))


def test_import_copy_error(tmp_path: Path):
    """
    Test handling of a file copy failure during import.
    """
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    ctx = Context(str(project_dir))
    project = ctx.get_project("")

    # Create a fake source file
    source_path = tmp_path / "fake_file.step"
    source_path.touch()

    # Simulate copy failure
    with patch("shutil.copy2", side_effect=shutil.Error("Copy failed")):
        with pytest.raises(ValueError, match="Failed to copy"):
            import_part_action(project, "step", "fake_part", str(source_path))
