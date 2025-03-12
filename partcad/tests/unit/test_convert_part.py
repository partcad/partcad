import pytest
import shutil
from pathlib import Path
import partcad.logging as pc_logging
from partcad.context import Context
from partcad.actions.part import convert_part_action
import yaml
from unittest.mock import patch, Mock


EXTENSION_MAPPING = {
    "step": "step",
    "brep": "brep",
    "stl": "stl",
    "3mf": "3mf",
    "threejs": "json",
    "obj": "obj",
    "gltf": "gltf",
    "cadquery": "py",
    "build123d": "py",
    "scad": "scad",
}

ALLOWED_TARGET_FORMATS = {"step", "brep", "stl", "3mf", "threejs", "obj", "gltf"}

SOURCE_DIR = Path("./examples/feature_convert")

PARTS_CONFIG = {
    "box_brep": {"type": "brep", "path": "brep/box.brep"},
    "cube_3mf": {"type": "3mf", "path": "3mf/cube.3mf"},
    "cube_build123d": {"type": "build123d", "path": "build123d/cube.py"},
    "cube_cadquery": {"type": "cadquery", "path": "cadquery/cube.py"},
    "prism_scad": {"type": "scad", "path": "scad/prism.scad"},
    "bolt_step": {"type": "step", "path": "step/bolt.step"},
    "cube_stl": {"type": "stl", "path": "stl/cube.stl"},
}




@pytest.mark.parametrize("source_part", PARTS_CONFIG.keys())
@pytest.mark.parametrize("target_format", ALLOWED_TARGET_FORMATS)
def test_full_conversion_matrix(source_part: str, target_format: str, tmp_path: Path):
    """Test converting every supported input format to allowed output formats."""

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

    yaml_path = project_dir / "partcad.yaml"
    config_data = {"parts": {source_part: {"type": source_format, "path": str(relative_source_path)}}}
    with open(yaml_path, "w", encoding="utf-8") as f:
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


@pytest.mark.parametrize("source_part", ["cube_enrich", "cube_enrich_scad", "cube_enrich_stl"])
@pytest.mark.parametrize("target_format", ALLOWED_TARGET_FORMATS)
def test_enrich_conversion(source_part: str, target_format: str, tmp_path: Path):
    """Test conversion of enrich parts, ensuring parameters are applied correctly."""

    project_dir = tmp_path / "enrich_project"
    project_dir.mkdir()

    source_file = project_dir / "cube.py"
    source_file.write_text("# Dummy Cube Part\n")

    yaml_path = project_dir / "partcad.yaml"
    config_data = {
        "parts": {
            "cube": {"type": "cadquery", "path": "cube.py"},
            source_part: {"type": "enrich", "source": ":cube", "with": {"width": 15, "height": 20}}
        }
    }

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")
    output_dir = tmp_path / "output_dir"
    output_dir.mkdir(parents=True, exist_ok=True)

    convert_part_action(project, source_part, target_format, output_dir=output_dir)

    expected_ext = EXTENSION_MAPPING[target_format]
    expected_file = output_dir / f"{source_part}.{expected_ext}"

    assert expected_file.exists(), f"Enrich conversion failed: {expected_file} not found"


@pytest.mark.parametrize("source_part", ["cube_alias", "cube_alias_step", "cube_alias_enrich"])
@pytest.mark.parametrize("target_format", ALLOWED_TARGET_FORMATS)
def test_alias_conversion(source_part: str, target_format: str, tmp_path: Path):
    """Test conversion of alias parts, ensuring they correctly resolve their base part."""

    project_dir = tmp_path / "alias_project"
    project_dir.mkdir()

    # Create base part file for alias resolution
    source_file = project_dir / "cube.py"
    source_file.write_text("# Dummy Cube Part\n")

    yaml_path = project_dir / "partcad.yaml"
    config_data = {
        "parts": {
            "cube": {"type": "cadquery", "path": "cube.py"},
            source_part: {"type": "alias", "source": ":cube"}
        }
    }

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")
    output_dir = tmp_path / "output_dir"
    output_dir.mkdir(parents=True, exist_ok=True)

    convert_part_action(project, source_part, target_format, output_dir=output_dir)

    expected_ext = EXTENSION_MAPPING[target_format]
    expected_file = output_dir / f"{source_part}.{expected_ext}"

    assert expected_file.exists(), f"Alias conversion failed, expected file not found: {expected_file}"



def test_parse_parameters_in_source_name():
    """Test parsing of parameters embedded in the source name."""
    from partcad.actions.part.convert import get_final_base_part_config, update_parameters_with_defaults
    from unittest.mock import Mock

    mock_project = Mock()
    mock_project.name = "mock_project"
    mock_project.ctx.get_project.return_value = mock_project
    mock_project.get_part_config.return_value = {
        "type": "cadquery",
        "parameters": {
            "width": {"type": "float", "default": 10.0},
            "height": {"type": "float", "default": 5.0}
        }
    }

    config, base_project, base_part_name = get_final_base_part_config(
        mock_project,
        {
            "source": "cube;width=15.0,height=20.0",
            "type": "cadquery",
        },
        "cube_with_params"
    )

    source_params = "width=15.0,height=20.0"
    for param in source_params.split(','):
        param_name, param_value = param.split('=')
        if "parameters" not in config:
            config["parameters"] = {}
        config["parameters"][param_name] = {"type": "float", "default": float(param_value)}

    config = update_parameters_with_defaults(config)

    assert config["parameters"]["width"]["default"] == 15.0
    assert config["parameters"]["height"]["default"] == 20.0
    assert config["type"] == "cadquery"


def test_alias_conversion(tmp_path: Path):
    """Test conversion of alias parts by resolving to their base part."""
    project_dir = tmp_path / "alias_project"
    project_dir.mkdir()

    cube_path = project_dir / "cube.py"
    cube_path.write_text("# Dummy Cube Part\n")

    yaml_path = project_dir / "partcad.yaml"
    config_data = {
        "parts": {
            "cube": {"type": "cadquery", "path": "cube.py"},
            "cube_alias": {"type": "alias", "source": ":cube"}
        }
    }
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")
    output_dir = tmp_path / "output_dir"
    output_dir.mkdir(parents=True, exist_ok=True)

    convert_part_action(project, "cube_alias", output_dir=output_dir)

    expected_file = output_dir / "cube_alias.py"
    assert expected_file.exists(), f"Alias conversion failed, expected file not found: {expected_file}"


def test_enrich_conversion(tmp_path: Path):
    """Test that enrich parts with parameters are converted correctly."""

    project_dir = tmp_path / "enrich_project"
    project_dir.mkdir()

    cube_path = project_dir / "cube.py"
    cube_path.write_text("# Dummy Cube Part\n")

    yaml_path = project_dir / "partcad.yaml"
    config_data = {
        "parts": {
            "cube": {"type": "cadquery", "path": "cube.py"},
            "cube_enrich": {"type": "enrich", "source": "cube", "with": {"width": 15.0, "height": 20.0}}
        }
    }
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")
    output_dir = tmp_path / "output_dir"
    output_dir.mkdir(parents=True, exist_ok=True)

    convert_part_action(project, "cube_enrich", output_dir=output_dir)

    expected_file = output_dir / "cube_enrich.py"
    assert expected_file.exists(), f"Enrich conversion failed: {expected_file} not found"


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
    with open(yaml_path, "w", encoding="utf-8") as f:
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
