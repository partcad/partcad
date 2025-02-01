import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

import pytest
import yaml
import rich_click as click
import partcad as pc
from partcad.context import Context
from partcad import Project
from partcad.conversion import convert_object


# Supported output formats
SUPPORTED_FORMATS = ["step", "brep", "stl", "3mf", "threejs", "obj", "gltf"]

# Directory containing source test files (adjust as needed)
SOURCE_DIR = Path("/workspaces/partcad/examples/feature_convert")

# Test parts configuration: each part's type and its relative source file path.
PARTS_CONFIG = {
    "box_brep": {"type": "brep", "path": "brep/box.brep"},
    "cube_3mf": {"type": "3mf", "path": "3mf/cube.3mf"},
    "cube_build123d": {"type": "build123d", "path": "build123d/cube.py"},
    "cube_cadquery": {"type": "cadquery", "path": "cadquery/cube.py"},
    "prism_scad": {"type": "scad", "path": "scad/prism.scad"},
    "bolt_step": {"type": "step", "path": "step/bolt.step"},
    "cube_stl": {"type": "stl", "path": "stl/cube.stl"},
}

@pytest.mark.parametrize("source_part", list(PARTS_CONFIG.keys()))
@pytest.mark.parametrize("target_format", SUPPORTED_FORMATS)
def test_part_conversion(source_part: str, target_format: str, tmp_path: Path):
    """
    Test converting a part from one format to another using convert_object.
    """
    source_config = PARTS_CONFIG[source_part]
    source_format = source_config["type"]
    source_file = source_config["path"]

    if source_format == target_format:
        pytest.skip("Skipping same-format conversion.")

    source_path = SOURCE_DIR / source_file
    if not source_path.exists():
        pytest.skip(f"Source file {source_path} not found.")

    # Create temporary project directory and copy source file.
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    dest_file = project_dir / source_file
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, dest_file)

    # Create a minimal partcad.yaml configuration file.
    config_data = {"parts": {source_part: source_config}}
    yaml_path = project_dir / "partcad.yaml"
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = pc.Context(str(project_dir))
    project = ctx.get_project("")
    assert project is not None, "Project not found."
    assert source_part in project.parts, f"Part {source_part} not found in project."
    part = project.get_part(source_part)
    assert part is not None, f"Failed to retrieve part {source_part}."

    # Check if the part supports conversion to target_format.
    render_method = f"render_{target_format}_async"
    if not hasattr(part, render_method):
        pytest.skip(
            f"Part {source_part} does not support conversion to {target_format} (missing method {render_method})."
        )

    # Override the conversion method with a dummy function that creates a file.
    async def dummy_render_async(ctx, project, output_dir):
        with open(output_dir, "w") as f:
            f.write("converted content")
    setattr(part, render_method, dummy_render_async)

    # Define output directory (converted file will be created here).
    output_dir = tmp_path / Path(source_file).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine expected file name using the base name from the source file.
    base_name = os.path.splitext(os.path.basename(source_file))[0]
    expected_file_name = f"{base_name}.{target_format}"
    output_file = output_dir / expected_file_name

    # Invoke conversion via the shared conversion logic.
    convert_object(project, source_part, target_format, str(output_dir), in_place=False)

    assert output_file.exists(), f"Converted file {output_file} was not created."

def test_generate_partcad_config(tmp_path: Path):
    """
    Test generating a PartCAD configuration file.
    """
    temp_dir = tmp_path / "config_test"
    temp_dir.mkdir()
    dummy_input = temp_dir / "dummy_input.stl"
    dummy_input.write_text("dummy stl content")

    config_data = {
        "parts": {
            "dummy_part": {"type": "stl", "path": str(dummy_input.relative_to(temp_dir))}
        }
    }
    yaml_path = temp_dir / "partcad.yaml"
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    with open(yaml_path, "r") as f:
        loaded = yaml.safe_load(f)
    assert "parts" in loaded
    assert "dummy_part" in loaded["parts"]
    assert str(dummy_input.relative_to(temp_dir)) == loaded["parts"]["dummy_part"]["path"]


def test_convert_invalid_file(tmp_path: Path):
    """
    Test conversion with an invalid input file using convert_object.
    """
    project_dir = tmp_path / "invalid_project"
    project_dir.mkdir()
    invalid_file = project_dir / "invalid.stl"
    invalid_file.write_text("invalid STL content")

    config_data = {
        "parts": {
            "invalid_part": {"type": "stl", "path": str(invalid_file.relative_to(project_dir))}
        }
    }
    yaml_path = project_dir / "partcad.yaml"
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = pc.Context(str(project_dir))
    project = ctx.get_project("")
    assert project is not None

    part = project.get_part("invalid_part")
    assert part is not None

    render_method = "render_stl_async"
    if not hasattr(part, render_method):
        pytest.skip("Part does not support conversion to stl.")

    # Create an output directory.
    output_dir = tmp_path / "output_dir"
    output_dir.mkdir()

    # Expect conversion to raise a RuntimeError due to invalid file content.
    with pytest.raises(RuntimeError, match="Failed to load") as exc_info:
        convert_object(project, "invalid_part", "step", str(output_dir), in_place=False)
    assert "failed" in str(exc_info.value).lower()


def test_conversion_missing_target_format(tmp_path: Path):
    """
    Test that missing target_format raises ValueError.
    """
    project_dir = tmp_path / "missing_target"
    project_dir.mkdir()
    part_name = "dummy_part"
    dummy_input = project_dir / "dummy.stl"
    dummy_input.write_text("dummy stl content")

    config_data = {"parts": {part_name: {"type": "stl", "path": str(dummy_input.relative_to(project_dir))}}}
    yaml_path = project_dir / "partcad.yaml"
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = pc.Context(str(project_dir))
    project = ctx.get_project("")
    # Assuming convert_object checks for a missing target_format.
    with pytest.raises(ValueError, match="Target format must be specified"):
        convert_object(project, part_name, None, str(dummy_input), in_place=False)


def test_in_place_conversion_update(tmp_path: Path, monkeypatch):
    """
    Test that in-place conversion updates the part configuration using convert_object.
    """
    project_dir = tmp_path / "in_place_update"
    project_dir.mkdir()
    part_name = "dummy_part"
    dummy_input = project_dir / "dummy.stl"
    dummy_input.write_text("dummy stl content")

    config_data = {
        "parts": {
            part_name: {"type": "stl", "path": str(dummy_input.relative_to(project_dir))}
        }
    }
    yaml_path = project_dir / "partcad.yaml"
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = pc.Context(str(project_dir))
    project = ctx.get_project("")
    part = project.get_part(part_name)

    # Attach a local config dictionary to the project
    project.config = {"parts": config_data["parts"].copy()}

    # Monkey-patch update_part_config to update the in-memory config.
    def fake_update_part_config(name, update):
        project.config["parts"][name].update(update)
    monkeypatch.setattr(project, "update_part_config", fake_update_part_config)

    # Monkey-patch get_part_config to return our in-memory config.
    def fake_get_part_config(name):
        return project.config["parts"].get(name, {})
    monkeypatch.setattr(project, "get_part_config", fake_get_part_config)

    async def dummy_render_step_async(ctx, project, output_dir):
        # Simulate conversion by creating the file.
        with open(output_dir, "w") as f:
            f.write("converted content")
    setattr(part, "render_step_async", dummy_render_step_async)

    output_dir = tmp_path / "output_in_place"
    output_dir.mkdir()
    # Expected output file is "dummy.step" in the output directory.
    output_file = output_dir / "dummy.step"

    convert_object(project, part_name, "step", str(output_dir), in_place=True)

    # Check that the file was created and configuration updated.
    assert output_file.exists()
    part_config = project.get_part_config(part_name)
    assert part_config.get("type") == "step"
    abs_project_path = os.path.abspath(project.path)
    abs_new_path = os.path.abspath(os.path.join(project.path, part_config.get("path")))
    assert abs_new_path == os.path.abspath(str(output_file))
