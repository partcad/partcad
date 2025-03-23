import shutil
from unittest.mock import patch
import pytest
import yaml
from pathlib import Path
from partcad.context import Context
from partcad.actions.part import import_part_action


SOURCE_DIR = Path("/workspaces/partcad/examples/feature_import")

PARTS_CONFIG = {
    "cube": {"type": "stl"},
}


@pytest.mark.parametrize("source_part", PARTS_CONFIG.keys())
def test_import_real_part(source_part: str, tmp_path: Path):
    """
    Test importing a real part file into a new project.
    """
    source_config = PARTS_CONFIG[source_part]
    part_type = source_config["type"]
    source_file = Path(source_config["path"]) if source_config.get("path") else Path(f"{source_part}.{part_type}")

    real_source_path = SOURCE_DIR / source_file
    if not real_source_path.exists():
        pytest.skip(f"Real source file {real_source_path} not found.")

    # Set up test project
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    # Create empty configuration
    config_data = {"parts": {}}
    yaml_path = project_dir / "partcad.yaml"
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")

    # Import part
    import_part_action(project, part_type, source_part, str(real_source_path))

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
