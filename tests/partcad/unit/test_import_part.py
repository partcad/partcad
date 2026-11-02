import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from partcad.actions.part import import_part_action
from partcad.context import Context

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


FCSTD = Path("tests/partcad/unit/data/import_fcstd/design_history.FCStd").resolve()


def _empty_project(tmp_path: Path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "partcad.yaml").write_text("parts: {}\n")
    return project_dir


@pytest.mark.parametrize("source_name", ["design_history.FCStd", "design_history.fcstd"])
def test_a_freecad_document_is_imported_under_the_name_its_type_looks_for(tmp_path: Path, source_name: str):
    """'fcstd' parts are '.FCStd' files, whatever the file handed over was called.

    The type is a declaration in '//builtin/import' and not a factory, and its
    parts are found at '<name>.FCStd' -- so a file copied in as '<name>.fcstd'
    was a part nothing could find on a file system that tells case apart.
    """
    source = tmp_path / source_name
    shutil.copyfile(FCSTD, source)
    project_dir = _empty_project(tmp_path)

    import_part_action(Context(str(project_dir)).get_project(""), "fcstd", "body", str(source))

    assert (project_dir / "body.FCStd").is_file()
    project = Context(str(project_dir)).get_project("")
    config = project.get_part_config("body")
    assert config["type"] == "fcstd"
    # The default it is found at is the file, so the declaration names no path.
    assert "path" not in config
    part = Context(str(project_dir)).get_part(":body")
    assert Path(part.path) == (project_dir / "body.FCStd")


def test_a_file_whose_extension_is_another_case_keeps_its_path(tmp_path: Path):
    """'part.STEP' is not where a 'step' part named 'part' is looked for: '<name>.step' is."""
    project_dir = _empty_project(tmp_path)
    (project_dir / "bracket.STEP").write_text("ISO-10303-21;\n")
    project = Context(str(project_dir)).get_project("")

    assert project.add_part("step", str(project_dir / "bracket.STEP"))

    config = Context(str(project_dir)).get_project("").get_part_config("bracket")
    assert config["type"] == "step"
    assert config["path"] == "bracket.STEP"
