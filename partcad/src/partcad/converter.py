from pathlib import Path
import shutil
import tempfile
from partcad.context import Context


def convert_cad_file(input_filename, input_type, output_filename, output_type):
    """
    Convert a CAD file from one format to another.

    Args:
        input_filename (str): Path to the input file.
        input_type (str): Format of the input file.
        output_filename (str): Path to save the output file.
        output_type (str): Format of the output file.
    """
    temp_dir = Path(tempfile.mkdtemp())  # Create a temporary directory for conversion
    try:
        temp_input_path = temp_dir / Path(input_filename).name
        shutil.copy(input_filename, temp_input_path)  # Copy input file to temp directory

        # Generate a temporary configuration file for PartCAD
        generate_partcad_config(temp_dir, input_type, temp_input_path)

        # Initialize PartCAD context and load the project
        ctx = Context(root_path=temp_dir, search_root=False)
        project = ctx.get_project("/")
        part = project.get_part("input_part")
        if not part:
            raise RuntimeError("Failed to load the input part.")

        # Export the part to the desired output format
        export_part(part, output_filename, output_type, ctx)
    finally:
        shutil.rmtree(temp_dir)  # Cleanup temporary files


def generate_partcad_config(temp_dir, input_type, temp_input_path):
    """
    Generate a temporary partcad.yaml configuration for processing.

    Args:
        temp_dir (Path): Temporary directory path.
        input_type (str): Input file format type.
        temp_input_path (Path): Path to the copied input file.
    """
    config_path = temp_dir / "partcad.yaml"
    config_content = f"""
parts:
  input_part:
    type: {input_type}
    path: {temp_input_path}
    """
    with open(config_path, "w") as config_file:
        config_file.write(config_content)


def export_part(part, output_filename, output_type, ctx):
    """
    Export a part to the desired format.

    Args:
        part: The part to export.
        output_filename (str): Path to save the exported file.
        output_type (str): Format of the exported file.
        ctx: The context required for export methods.
    """
    export_methods = {
        "step": "render_step",
        "brep": "render_brep",
        "stl": "render_stl",
        "3mf": "render_3mf",
        "threejs": "render_threejs",
        "obj": "render_obj",
        "gltf": "render_gltf",
        "markdown": "render_markdown",
        "txt": "render_txt",
    }

    export_method = export_methods.get(output_type)
    if not export_method:
        raise ValueError(f"Unsupported export format: {output_type}")

    if not hasattr(part, export_method):
        raise RuntimeError(f"Part does not support export to '{output_type}'.")

    # Call the appropriate export method, passing the required context and filepath
    getattr(part, export_method)(ctx=ctx, filepath=output_filename)
