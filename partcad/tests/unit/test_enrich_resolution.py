import os
import shutil
from pathlib import Path
import pytest
import yaml
from partcad.context import Context
from partcad import Project
from partcad.actions.part_actions import resolve_enrich_action
import partcad.logging as pc_logging

# Source directory with real test files
SOURCE_DIR = Path("/workspaces/partcad/examples/feature_convert")


def test_resolve_enrich_part(tmp_path: Path):
    """Test resolving enrich parts in a temporary project structure."""

    part_config = {
        "type": "enrich",
        "source": "//:bolt",
        "with": {"height": 4, "width": 4},
    }

    real_source_path = SOURCE_DIR / "step/bolt.step"
    enrich_part_name = "bolt_enrich"
    if not real_source_path.exists():
        pytest.skip(f"Real source file {real_source_path} not found.")

    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    source_path = project_dir / "step/bolt.step"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(real_source_path, source_path)

    relative_source_path = source_path.relative_to(project_dir)

    # Create project configuration
    yaml_path = project_dir / "partcad.yaml"
    config_data = {
        "parts": {
            "bolt": {"type": "step", "path": "step/bolt.step"},
            enrich_part_name: part_config
        }
    }
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")

    assert (project_dir / relative_source_path).exists(), f"Missing source file: {relative_source_path}"

    resolve_enrich_action(project, enrich_part_name)

    # Reload project to ensure changes are applied
    ctx = Context(str(project_dir))
    project = ctx.get_project("")
    updated_config = project.get_part_config(enrich_part_name)

    assert updated_config is not None, "Resolved part config should exist."
    assert updated_config["type"] == "step", "Resolved part type should be 'step'."
    assert "path" in updated_config, "Resolved part should have a valid path."
    assert (Path(project.path) / updated_config["path"]).exists(), "Resolved part file should exist."

    pc_logging.info(f"Successfully resolved enrich part: {enrich_part_name}")


def test_resolve_enrich_invalid_part(tmp_path: Path):
    """Test resolving a non-existent enrich part."""
    project_dir = tmp_path / "invalid_project"
    project_dir.mkdir()
    yaml_path = project_dir / "partcad.yaml"
    config_data = {"parts": {}}
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")
    part_name = "non_existent_part"

    pc_logging.info("Testing resolution of a non-existent enrich part...")
    with pytest.raises(ValueError, match=f"Invalid or missing enrich part '{part_name}' in project '{project.name}'."):
        resolve_enrich_action(project, part_name)

    pc_logging.info("Handled non-existent enrich part correctly.")


def test_resolve_enrich_with_missing_source(tmp_path: Path):
    """Test resolving an enrich part with a missing source."""
    project_dir = tmp_path / "missing_source_project"
    project_dir.mkdir()
    yaml_path = project_dir / "partcad.yaml"
    config_data = {
        "parts": {
            "invalid_enrich": {
                "type": "enrich",
                "source": "missing_source"
            }
        }
    }
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")

    pc_logging.info("Testing resolution of an enrich part with missing source...")
    with pytest.raises(ValueError, match="Source part 'missing_source' has no valid path in project '//'."):
        resolve_enrich_action(project, "invalid_enrich")

    pc_logging.info("Handled missing source for enrich part correctly.")


def test_resolve_enrich_with_invalid_path(tmp_path: Path):
    """Test resolving an enrich part where the source file does not exist."""
    project_dir = tmp_path / "invalid_path_project"
    project_dir.mkdir()
    yaml_path = project_dir / "partcad.yaml"
    config_data = {
        "parts": {
            "invalid_enrich": {
                "type": "enrich",
                "source": "//:non_existing_part"
            }
        }
    }
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")

    pc_logging.info("Testing resolution of an enrich part with a non-existing source file...")
    with pytest.raises(ValueError, match="Source part 'non_existing_part' has no valid path in project '//'."):
        resolve_enrich_action(project, "invalid_enrich")

    pc_logging.info("Handled missing source path for enrich part correctly.")
