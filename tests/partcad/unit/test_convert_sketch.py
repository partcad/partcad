import pytest
import shutil
from pathlib import Path
import yaml

import partcad as pc
from partcad.context import Context
from partcad.actions.sketch import convert_sketch_action
from partcad.shape import SKETCH_EXTENSION_MAPPING


SKETCH_INPUTS = {
    "cylinder_svg": {"type": "svg", "path": "svg/cylinder.svg"},
    "slot_dxf": {"type": "dxf", "path": "dxf/t-slot.dxf"},
    "circle_basic": {"type": "basic"},
    "clock_build123d": {"type": "build123d", "path": "build123d/clock.py"},
    "sketch_cadquery": {"type": "cadquery", "path": "cadquery/sketch.py"},
}

ALLOWED_TARGETS = ["svg", "dxf"]

SOURCE_DIR = Path("./examples/feature_convert_sketch")


@pytest.mark.parametrize("sketch_name", sorted(list(SKETCH_INPUTS.keys())))
@pytest.mark.parametrize("target_format", sorted(ALLOWED_TARGETS))
def test_sketch_conversion(sketch_name, target_format, tmp_path: Path):
    """Convert each supported sketch input to all allowed output formats."""
    
    if "basic" in sketch_name:
        pytest.skip()

    sketch_info = SKETCH_INPUTS[sketch_name]
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    if "path" in sketch_info:
        source_file = SOURCE_DIR / sketch_info["path"]
        if not source_file.exists():
            pytest.skip(f"Missing file: {source_file}")
        sketch_path = project_dir / sketch_info["path"]
        sketch_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, sketch_path)
        relative_path = sketch_path.relative_to(project_dir)
    else:
        relative_path = None

    config = {"type": sketch_info["type"]}
    if relative_path:
        config["path"] = str(relative_path)

    yaml_path = project_dir / "partcad.yaml"
    yaml.safe_dump({"sketches": {sketch_name: config}}, yaml_path.open("w"))

    ctx = Context(str(project_dir))
    project = ctx.get_project("")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    if sketch_info["type"] == target_format:
        pytest.skip("Skipping same-format conversion.")

    convert_sketch_action(project, sketch_name, target_format, output_dir=str(output_dir))

    expected_file = output_dir / f"{sketch_name}.{SKETCH_EXTENSION_MAPPING[target_format]}"
    assert expected_file.exists(), f"Missing output file: {expected_file}"


def test_enrich_sketch_conversion(tmp_path: Path):
    """Test that enrich sketches are resolved and converted correctly."""

    project_dir = tmp_path / "enrich_project"
    project_dir.mkdir()

    base_svg = SOURCE_DIR / "svg/cylinder.svg"
    base_path = project_dir / "cylinder.svg"
    base_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base_svg, base_path)

    config_data = {
        "sketches": {
            "cylinder": {"type": "svg", "path": "cylinder.svg"},
            "cylinder_enrich": {"type": "enrich", "source": ":cylinder", "with": {}},
        }
    }

    yaml_path = project_dir / "partcad.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")
    output_dir = tmp_path / "output_dir"
    output_dir.mkdir(parents=True, exist_ok=True)

    convert_sketch_action(project, "cylinder_enrich", output_dir=output_dir)

    expected_file = output_dir / "cylinder_enrich.svg"
    assert expected_file.exists(), f"Enrich sketch conversion failed: {expected_file} not found"


def test_alias_sketch_conversion(tmp_path: Path):
    """Test conversion of alias sketches by resolving to their base sketch."""
    project_dir = tmp_path / "alias_project"
    project_dir.mkdir()

    base_svg = SOURCE_DIR / "svg/cylinder.svg"
    base_path = project_dir / "cylinder.svg"
    base_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base_svg, base_path)

    yaml_path = project_dir / "partcad.yaml"
    config_data = {
        "sketches": {
            "cylinder": {"type": "svg", "path": "cylinder.svg"},
            "cylinder_alias": {"type": "alias", "source": ":cylinder"},
        }
    }
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")
    output_dir = tmp_path / "output_dir"
    output_dir.mkdir(parents=True, exist_ok=True)

    convert_sketch_action(project, "cylinder_alias", target_format="dxf", output_dir=output_dir)

    expected_file = output_dir / "cylinder_alias.dxf"
    assert expected_file.exists(), f"Alias sketch conversion failed, expected file not found: {expected_file}"


def test_sketch_dry_run(tmp_path: Path):
    """Ensure that dry-run conversion does not produce output files."""

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    source_path = project_dir / "cylinder.svg"
    shutil.copy2(SOURCE_DIR / "svg/cylinder.svg", source_path)

    config_data = {"sketches": {"cylinder": {"type": "svg", "path": "cylinder.svg"}}}
    yaml.safe_dump(config_data, (project_dir / "partcad.yaml").open("w"))

    ctx = Context(str(project_dir))
    project = ctx.get_project("")
    out = tmp_path / "out"
    out.mkdir()

    convert_sketch_action(project, "cylinder", "dxf", output_dir=str(out), dry_run=True)
    assert not any(out.iterdir()), "Dry-run should not produce output files"
