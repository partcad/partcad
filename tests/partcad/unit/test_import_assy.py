from pathlib import Path

import pytest
import yaml

from partcad.actions.assembly import import_assy_action
from partcad.context import Context

ROOT_DIR = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = ROOT_DIR / "examples/feature_import"
REFERENCE_DIR = EXAMPLES_DIR / "AeroAssembly_assy_example"
ASSEMBLY_FILE = EXAMPLES_DIR / "AeroAssembly.step"


def load_yaml(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def compare_dicts(d1, d2, path=""):
    if isinstance(d1, dict) and isinstance(d2, dict):
        keys1, keys2 = set(d1.keys()), set(d2.keys())
        if keys1 != keys2:
            pytest.fail(f"Key mismatch at {path}: {keys1 ^ keys2}")
        for key in keys1:
            compare_dicts(d1[key], d2[key], path + f".{key}")
    elif isinstance(d1, list) and isinstance(d2, list):
        if len(d1) != len(d2):
            pytest.fail(f"List length mismatch at {path}: {len(d1)} != {len(d2)}")
        for i, (item1, item2) in enumerate(zip(d1, d2)):
            compare_dicts(item1, item2, path + f"[{i}]")
    else:
        if d1 != d2:
            pytest.fail(f"Value mismatch at {path}: {d1} != {d2}")


def adjust_reference_paths(reference_data):
    """
    Replaces 'AeroAssembly_assy_example' with 'AeroAssembly'
    in all paths to properly compare expected and generated results.
    """
    if isinstance(reference_data, dict):
        return {key: adjust_reference_paths(value) for key, value in reference_data.items()}
    elif isinstance(reference_data, list):
        return [adjust_reference_paths(item) for item in reference_data]
    elif isinstance(reference_data, str):
        return reference_data.replace("AeroAssembly_assy_example", "AeroAssembly")
    return reference_data


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
    """Tests the import of assembly and compares output YAML files with reference files."""
    project, project_dir = setup_test_project

    assert ASSEMBLY_FILE.exists(), f"File {ASSEMBLY_FILE} is missing."

    assy_name = import_assy_action(project, "step", str(ASSEMBLY_FILE), {})

    generated_assy_file = project_dir / Path(assy_name) / f"{assy_name}.assy"
    reference_assy_file = REFERENCE_DIR / f"{assy_name}.assy"

    assert generated_assy_file.exists(), f"File {generated_assy_file} is missing."
    assert reference_assy_file.exists(), f"Reference file {reference_assy_file} is missing."

    def load_yaml(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    generated_yaml = load_yaml(generated_assy_file)
    reference_yaml = load_yaml(reference_assy_file)

    reference_yaml_adjusted = adjust_reference_paths(reference_yaml)

    assert generated_yaml == reference_yaml_adjusted, "Generated YAML does not match the expected file!"

    # Validate all .yaml files in the directory
    for generated_yaml_file in project_dir.glob("**/*.yaml"):
        if generated_yaml_file.name == "partcad.yaml":
            continue

        reference_yaml_file = REFERENCE_DIR / generated_yaml_file.relative_to(project_dir)

        assert reference_yaml_file.exists(), f"Reference YAML file {reference_yaml_file} is missing!"

        generated_yaml = load_yaml(generated_yaml_file)
        reference_yaml = load_yaml(reference_yaml_file)

        reference_yaml_adjusted = adjust_reference_paths(reference_yaml)
        assert generated_yaml == reference_yaml_adjusted, f"Mismatch in YAML file: {generated_yaml_file}"


def test_import_assembly_as_its_compound(setup_test_project):
    """'pc import assembly --compound': the STEP file as one part of the package, as it is.

    A STEP file read as a part is one shape holding every solid in it, which is
    the compound of the assembly it holds - so the file is copied and declared
    as a 'step' part, and nothing else is written: no part per solid, no ASSY.
    """
    project, project_dir = setup_test_project

    name = import_assy_action(project, "step", str(ASSEMBLY_FILE), {}, compound=True)

    assert name == "AeroAssembly"
    assert (project_dir / "AeroAssembly.step").read_bytes() == ASSEMBLY_FILE.read_bytes()
    config = load_yaml(project_dir / "partcad.yaml")
    assert config["parts"] == {"AeroAssembly": {"type": "step"}}
    assert not config.get("assemblies")
    assert not (project_dir / "AeroAssembly").exists()


def test_a_compound_import_refuses_a_part_name_in_use(setup_test_project):
    project, _project_dir = setup_test_project
    import_assy_action(project, "step", str(ASSEMBLY_FILE), {}, compound=True)

    with pytest.raises(ValueError, match="already has a part named 'AeroAssembly'"):
        import_assy_action(project, "step", str(ASSEMBLY_FILE), {}, compound=True)


def test_import_part_refuses_an_assembly(setup_test_project):
    """'pc import part AeroAssembly.step': an assembly read as a part loses its parts, so it is not done unasked."""
    from partcad.actions.part import import_part_action
    from partcad.assembly_file import AssemblyNotPart

    project, project_dir = setup_test_project

    with pytest.raises(AssemblyNotPart, match="holds an assembly"):
        import_part_action(project, "step", "AeroAssembly", str(ASSEMBLY_FILE))

    assert not (project_dir / "AeroAssembly.step").exists()
    assert load_yaml(project_dir / "partcad.yaml") == {"parts": {}}


def test_import_part_compound_imports_an_assembly_as_one_part(setup_test_project):
    """'pc import part --compound AeroAssembly.step': the same part 'pc import assembly --compound' makes."""
    from partcad.actions.part import import_part_action

    project, project_dir = setup_test_project

    import_part_action(project, "step", "AeroAssembly", str(ASSEMBLY_FILE), compound=True)

    assert (project_dir / "AeroAssembly.step").read_bytes() == ASSEMBLY_FILE.read_bytes()
    assert load_yaml(project_dir / "partcad.yaml")["parts"] == {"AeroAssembly": {"type": "step"}}


def test_import_invalid_file(setup_test_project):
    """Tests handling of an invalid/missing assembly file."""
    project, _ = setup_test_project

    with pytest.raises(FileNotFoundError, match="File 'invalid_file.step' not found."):
        import_assy_action(project, "step", "invalid_file.step", {})
