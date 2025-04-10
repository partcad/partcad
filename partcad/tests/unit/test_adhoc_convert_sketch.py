import pytest
import shutil
import tempfile
from pathlib import Path
from partcad.adhoc.convert import convert_sketch_file, generate_partcad_config


SKETCH_INPUT_FORMATS = ["svg"]
SKETCH_OUTPUT_FORMATS = ["svg", "dxf"]

SKETCH_TEST_FILES = {
    "svg": "cylinder.svg",
    "dxf": "t-slot.dxf",
    "build123d": "clock.py",
    "cadquery": "sketch.py",
}


@pytest.fixture(params=SKETCH_TEST_FILES.keys())
def temp_sketch_file(tmp_path, request):
    """Copy test sketch file into a temporary directory."""
    input_format = request.param
    source_file = Path(f"examples/feature_convert_sketch/{input_format}/{SKETCH_TEST_FILES[input_format]}")
    test_file = tmp_path / SKETCH_TEST_FILES[input_format]
    assert source_file.exists(), f"Sketch test file {source_file} not found."
    test_file.write_bytes(source_file.read_bytes())
    return test_file, input_format


@pytest.fixture(params=SKETCH_OUTPUT_FORMATS)
def temp_sketch_output_file(tmp_path, request):
    """Create an output sketch file path for a given format."""
    output_format = request.param
    return tmp_path / f"sketch_output.{output_format}", output_format


def test_convert_sketch_file(temp_sketch_file, temp_sketch_output_file):
    """Test sketch file conversion from input to output formats."""
    input_file, input_format = temp_sketch_file
    output_file, output_format = temp_sketch_output_file
    if input_format == output_format:
        pytest.skip(f"Skipping same-format conversion: {input_format} -> {output_format}")
    convert_sketch_file(str(input_file), input_format, str(output_file), output_format)
    assert output_file.exists(), f"Sketch conversion failed: {input_format} -> {output_format}"


def test_convert_invalid_sketch_file():
    """Test conversion with an invalid or corrupted sketch file."""
    temp_dir = tempfile.mkdtemp()
    invalid_file = Path(temp_dir) / "invalid.svg"
    invalid_file.write_text("invalid SVG content")
    output_file = Path(temp_dir) / "output.dxf"
    with pytest.raises(RuntimeError, match="Failed to convert sketch"):
        convert_sketch_file(str(invalid_file), "svg", str(output_file), "dxf")
    shutil.rmtree(temp_dir)


def test_generate_sketch_config(temp_sketch_file):
    """Test temporary sketch config generation."""
    temp_dir = Path(tempfile.mkdtemp())
    input_file, input_type = temp_sketch_file
    generate_partcad_config(temp_dir, input_type, input_file, kind="sketch")
    config_path = temp_dir / "partcad.yaml"
    assert config_path.exists()
    content = config_path.read_text()
    assert "input_sketch" in content
    assert str(input_file) in content
    shutil.rmtree(temp_dir)
