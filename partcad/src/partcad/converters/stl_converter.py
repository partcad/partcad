from pathlib import Path
from OCP.TopoDS import TopoDS_Shape
from OCP.StlAPI import StlAPI_Reader, StlAPI_Writer
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.BRepTools import BRepTools
from OCP.BRepMesh import BRepMesh_IncrementalMesh
import io
from .base_converter import BaseConverter
from .. import logging


def is_solid(shape: TopoDS_Shape) -> bool:
    """Check if the given shape is a solid."""
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    return explorer.More()


def simplify_shape(shape: TopoDS_Shape) -> TopoDS_Shape:
    """Simplify the given shape using BRepBuilderAPI_Copy."""
    copier = BRepBuilderAPI_Copy(shape)
    return copier.Shape()


def dump_shape(shape: TopoDS_Shape):
    """Dump the details of the given shape for debugging."""
    dump = io.BytesIO()  # Use BytesIO instead of StringIO
    BRepTools.Dump_s(shape, dump)
    dump_value = dump.getvalue().decode('utf-8')  # Decode bytes to string
    # logging.info(f"Shape dump:\n{dump_value}")


class StlConverter(BaseConverter):
    def read(self) -> TopoDS_Shape:
        """Reads an STL file and returns a TopoDS_Shape."""
        stl_reader = StlAPI_Reader()
        shape = TopoDS_Shape()
        if not stl_reader.Read(shape, str(self.input_file)):
            raise RuntimeError(f"Failed to read STL file: {self.input_file}")
        return shape


    def write(self, shape: TopoDS_Shape, tolerance=0.5, angular_tolerance=0.5, ascii=False) -> None:
        """
        Writes a TopoDS_Shape to an STL file with mesh simplification.

        Parameters:
        - tolerance: Linear deflection tolerance for mesh generation (larger value = fewer triangles).
        - angular_tolerance: Angular deflection tolerance for mesh generation.
        - ascii: Boolean flag to determine if STL should be in ASCII format.
        """
        logging.info(f"Attempting to write STL file: {self.output_file}")

        # Check if the shape is valid
        analyzer = BRepCheck_Analyzer(shape)
        if not analyzer.IsValid():
            raise RuntimeError(f"The shape is not valid and cannot be exported to STL: {shape}")

        # Check if the shape is solid
        if not is_solid(shape):
            raise RuntimeError("The shape is not a solid and cannot be exported to STL.")

        # Simplify shape if needed
        simplified_shape = simplify_shape(shape)
        logging.info("Shape simplified for STL export.")

        # Generate mesh for the shape with higher tolerance for simplification
        logging.info(f"Generating mesh with tolerance={tolerance} and angular_tolerance={angular_tolerance}...")
        BRepMesh_IncrementalMesh(
            simplified_shape,
            theLinDeflection=tolerance,
            isRelative=True,
            theAngDeflection=angular_tolerance,
            isInParallel=True,
        )

        # Log shape details
        logging.info("Mesh generation completed.")
        dump_shape(simplified_shape)

        stl_writer = StlAPI_Writer()
        stl_writer.ASCIIMode = ascii

        # Ensure the directory exists
        self.output_file.parent.mkdir(parents=True, exist_ok=True)

        # Try writing the file
        temp_output = self.output_file.with_suffix(".temp.stl")
        try:
            if not stl_writer.Write(simplified_shape, str(temp_output)):
                raise RuntimeError(f"Failed to write STL file to temporary location: {temp_output}")
            temp_output.rename(self.output_file)
            logging.info(f"Successfully wrote STL file: {self.output_file}")
        except Exception as e:
            logging.error(f"Error writing STL file: {e}")
            if temp_output.exists():
                temp_output.unlink()  # Remove temporary file if it exists
            raise
