import os
import shutil
from pathlib import Path
import pytest
import yaml
from partcad.context import Context
from partcad import Project
from partcad.actions.part_actions import convert_part_action
import partcad.logging as pc_logging  # Logging

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

SUPPORTED_FORMATS = list(EXTENSION_MAPPING.keys())

# Source directory with real test files
SOURCE_DIR = Path("/workspaces/partcad/examples/feature_convert")

# Test parts configuration
PARTS_CONFIG = {
    "box_brep": {"type": "brep", "path": "brep/box.brep"},
    "cube_3mf": {"type": "3mf", "path": "3mf/cube.3mf"},
    "bolt_step": {"type": "step", "path": "step/bolt.step"},
    "cube_stl": {"type": "stl", "path": "stl/cube.stl"},
}

@pytest.mark.parametrize("source_part", PARTS_CONFIG.keys())
@pytest.mark.parametrize("target_format", SUPPORTED_FORMATS)
def test_full_conversion_matrix(source_part: str, target_format: str, tmp_path: Path):
    """Test converting every supported input format to every supported output format."""

    source_config = PARTS_CONFIG[source_part]
    source_format, source_file = source_config["type"], Path(source_config["path"])

    if source_format == target_format:
        pytest.skip("Skipping same-format conversion.")

    real_source_path = SOURCE_DIR / source_file
    if not real_source_path.exists():
        pytest.skip(f"Real source file {real_source_path} not found.")

    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    source_path = project_dir / source_file
    source_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(real_source_path, source_path)

    relative_source_path = source_path.relative_to(project_dir)

    # Create project configuration
    yaml_path = project_dir / "partcad.yaml"
    config_data = {"parts": {source_part: {"type": source_format, "path": str(relative_source_path)}}}
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")
    output_dir = tmp_path / "output_dir"
    output_dir.mkdir(parents=True, exist_ok=True)

    assert (project_dir / relative_source_path).exists(), f"Missing source file: {relative_source_path}"

    pc_logging.info(f"Converting {source_part} ({source_format}) -> {target_format}")

    convert_part_action(project, source_part, target_format, output_dir=str(output_dir))

    expected_ext = EXTENSION_MAPPING[target_format]
    expected_files = list(output_dir.glob(f"*.{expected_ext}"))

    assert expected_files, f"No converted file found in {output_dir}"
    pc_logging.info(f"Conversion successful: {source_part} -> {target_format}")


def test_invalid_file_conversion(tmp_path: Path):
    """Test conversion when the input file does not exist."""

    project_dir = tmp_path / "invalid_file_project"
    project_dir.mkdir()

    yaml_path = project_dir / "partcad.yaml"
    config_data = {"parts": {}}
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")

    part_name = "cube_stl"
    project.add_part("stl", "invalid.stl", {})

    pc_logging.info("Testing conversion with missing file...")

    with pytest.raises(ValueError, match=f"Object '{part_name}' not found in project configuration."):
        convert_part_action(project, part_name, "step", output_dir=str(tmp_path))

    pc_logging.info("Handled missing file scenario correctly.")


def test_convert_with_dry_run(tmp_path: Path):
    """Test conversion in dry-run mode (without actual changes)."""

    project_dir = tmp_path / "dry_run_project"
    project_dir.mkdir()

    part_name = "cube"
    real_source_path = SOURCE_DIR / "stl/cube.stl"
    input_file = project_dir / "cube.stl"

    if not real_source_path.exists():
        pytest.skip(f"Real STL file {real_source_path} not found.")

    shutil.copy2(real_source_path, input_file)

    yaml_path = project_dir / "partcad.yaml"
    config_data = {"parts": {part_name: {"type": "stl", "path": str(input_file.relative_to(project_dir))}}}
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")
    output_dir = tmp_path / "output_dir"
    output_dir.mkdir(parents=True, exist_ok=True)

    pc_logging.info(f"Performing dry-run conversion for {part_name}...")

    convert_part_action(project, part_name, "step", output_dir=str(output_dir), dry_run=True)

    expected_files = list(output_dir.glob(f"*.step"))
    assert not expected_files, "Dry-run mode should not create files."

    pc_logging.info("Dry-run conversion verified successfully.")


def test_invalid_format_conversion(tmp_path: Path):
    """Test handling of unsupported conversion format."""

    project_dir = tmp_path / "invalid_format_project"
    project_dir.mkdir()

    part_name = "cube"
    real_source_path = SOURCE_DIR / "stl/cube.stl"
    input_file = project_dir / "cube.stl"

    if not real_source_path.exists():
        pytest.skip(f"Real STL file {real_source_path} not found.")

    shutil.copy2(real_source_path, input_file)

    yaml_path = project_dir / "partcad.yaml"
    config_data = {"parts": {part_name: {"type": "stl", "path": "cube.stl"}}}
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")

    pc_logging.info("Testing conversion with invalid format...")

    with pytest.raises(ValueError, match="Target format must be specified"):
        convert_part_action(project, part_name, "")

    pc_logging.info("Invalid format conversion handled correctly.")
