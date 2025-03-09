import pytest
import yaml
import shutil
from pathlib import Path
from partcad.context import Context
from partcad.actions.assy_actions import import_assy_action
from partcad import logging as pc_logging


EXAMPLES_DIR = Path("/workspaces/partcad/examples/feature_import")
REFERENCE_DIR = EXAMPLES_DIR / "AeroAssembly_assy_example"
ASSEMBLY_FILE = EXAMPLES_DIR / "AeroAssembly.step"


@pytest.fixture
def setup_test_project(tmp_path):
    """Sets up a temporary test project."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    config_data = {"parts": {}}
    yaml_path = project_dir / "partcad.yaml"
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_data, f)

    ctx = Context(str(project_dir))
    project = ctx.get_project("")

    return project, project_dir


def test_import_assembly(setup_test_project, tmp_path):
    """Tests the import of assembly and compares the output with reference files."""
    project, project_dir = setup_test_project

    assert ASSEMBLY_FILE.exists(), f"File {ASSEMBLY_FILE} is missing."

    assy_name = import_assy_action(project, "step", str(ASSEMBLY_FILE), {})

    generated_assy_file = project_dir / Path(assy_name) / f"{assy_name}.assy"

    assert generated_assy_file.exists(), f"File {generated_assy_file} is missing."

    reference_assy_file = REFERENCE_DIR / f"{assy_name}.assy"
    assert reference_assy_file.exists(), f"Reference file {reference_assy_file} is missing!"


def test_import_invalid_file(setup_test_project):
    """Tests handling of an invalid/missing assembly file."""
    project, _ = setup_test_project

    with pytest.raises(FileNotFoundError, match="File 'invalid_file.step' not found."):
        import_assy_action(project, "step", "invalid_file.step", {})
