import pytest
import shutil
import tempfile
from pathlib import Path
from partcad.context import Context
from partcad.adhoc.convert import convert_cad_file, generate_partcad_config


OUTPUT_FORMATS = ["stl", "step", "brep", "3mf", "threejs", "obj"]

TEST_FILES = {
    "stl": "cube.stl",
    "step": "bolt.step",
    "brep": "box.brep",
    "3mf": "cube.3mf",
    "scad": "prism.scad",
    "cadquery": "cube.py",
    "build123d": "cube.py",
}


@pytest.fixture(params=TEST_FILES.keys())
def temp_cad_file(tmp_path, request):
    """
    Fixture to copy test files from 'examples/feature_convert' into a temporary test directory.
    This simulates different input formats for conversion.
    """
    input_format = request.param
    source_file = Path(f"examples/feature_convert/{input_format}/{TEST_FILES[input_format]}")
    test_file = tmp_path / TEST_FILES[input_format]

    if not source_file.exists():
        pytest.skip(f"Skipping: Test file {source_file} not found.")

    test_file.write_bytes(source_file.read_bytes())  # Copy the file for testing
    return test_file, input_format


@pytest.fixture(params=OUTPUT_FORMATS)
def temp_output_file(tmp_path, request):
    """
    Fixture to create an output file for each format.
    This ensures conversion is tested for all supported output types.
    """
    output_format = request.param
    return tmp_path / f"output.{output_format}", output_format


def test_generate_partcad_config(temp_cad_file):
    """Test that a temporary PartCAD configuration file is correctly generated."""
    temp_dir = Path(tempfile.mkdtemp())
    input_file, input_type = temp_cad_file
    generate_partcad_config(temp_dir, input_type, input_file)

    config_path = temp_dir / "partcad.yaml"
    assert config_path.exists()

    with open(config_path, "r") as f:
        content = f.read()
        assert "input_part" in content
        assert str(input_file) in content

    shutil.rmtree(temp_dir)


def test_convert_cad_file(temp_cad_file, temp_output_file):
    """Test CAD file conversion from each input format to each output format."""
    input_file, input_format = temp_cad_file
    output_file, output_format = temp_output_file

    # Skip same-format conversion
    if input_format == output_format:
        pytest.skip(f"Skipping same-format conversion: {input_format} -> {output_format}")

    convert_cad_file(input_file, input_format, output_file, output_format)
    assert output_file.exists(), f"Conversion failed: {input_format} -> {output_format}"


def test_convert_invalid_file():
    """Test conversion with an invalid or corrupted input file."""
    temp_dir = tempfile.mkdtemp()
    invalid_file = Path(temp_dir) / "invalid.stl"
    invalid_file.write_text("invalid STL content")  # Corrupt STL file

    output_file = Path(temp_dir) / "output.step"

    with pytest.raises(RuntimeError, match="Failed to convert:"):
        convert_cad_file(invalid_file, "stl", output_file, "step")

    shutil.rmtree(temp_dir)
