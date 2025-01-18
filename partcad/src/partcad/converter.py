import os
from OCP.TopoDS import TopoDS_Shape
from OCP.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from OCP.StlAPI import StlAPI_Reader, StlAPI_Writer
from OCP.BRepTools import BRepTools
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from lib3mf import Wrapper, Position, Triangle
from . import logging


class CADConverter:
    """
    Handles CAD file conversion between supported formats (STEP, STL, 3MF, BREP).
    """
    CONVERTERS = {"step", "stl", "3mf", "brep"}

    @staticmethod
    def is_supported_format(fmt: str) -> bool:
        """Check if the format is supported."""
        return fmt.lower() in CADConverter.CONVERTERS

    @staticmethod
    def convert(input_file: str, output_file: str, input_format: str, output_format: str) -> None:
        """Perform file conversion between any supported formats."""
        logging.info(f"Converting from {input_format} to {output_format}")

        if not CADConverter.is_supported_format(input_format):
            raise ValueError(f"Unsupported input format: {input_format}")
        if not CADConverter.is_supported_format(output_format):
            raise ValueError(f"Unsupported output format: {output_format}")

        shape = CADConverter._read_shape(input_file, input_format)
        CADConverter._write_shape(shape, output_file, output_format)

    @staticmethod
    def _read_shape(file_path: str, file_format: str) -> TopoDS_Shape:
        """Read a CAD file and return its shape."""
        file_format = file_format.lower()

        if file_format == "step":
            return CADConverter._read_step(file_path)
        elif file_format == "stl":
            return CADConverter._read_stl(file_path)
        elif file_format == "brep":
            return CADConverter._read_brep(file_path)
        else:
            raise ValueError(f"Unsupported input format: {file_format}")

    @staticmethod
    def _write_shape(shape: TopoDS_Shape, file_path: str, file_format: str):
        """Write a shape to a CAD file."""
        file_format = file_format.lower()

        if file_format == "step":
            CADConverter._write_step(shape, file_path)
        elif file_format == "stl":
            CADConverter._write_stl(shape, file_path)
        elif file_format == "brep":
            CADConverter._write_brep(shape, file_path)
        elif file_format == "3mf":
            temp_stl = CADConverter._write_temp_stl(shape)
            try:
                CADConverter._convert_stl_to_3mf(temp_stl, file_path)
            finally:
                os.remove(temp_stl)
        else:
            raise ValueError(f"Unsupported output format: {file_format}")

    @staticmethod
    def _read_step(step_file: str) -> TopoDS_Shape:
        """Read a STEP file and return its shape."""
        reader = STEPControl_Reader()
        status = reader.ReadFile(step_file)
        if status != 1:
            raise ValueError("Failed to read the STEP file")
        reader.TransferRoots()
        return reader.OneShape()

    @staticmethod
    def _write_step(shape: TopoDS_Shape, step_file: str):
        """Write a shape to a STEP file."""
        writer = STEPControl_Writer()
        mode = STEPControl_AsIs  # Use STEPControl_AsIs for default mode
        writer.Transfer(shape, mode)
        if writer.Write(step_file) != 1:
            raise IOError(f"Failed to write STEP file: {step_file}")

    @staticmethod
    def _read_stl(stl_file: str) -> TopoDS_Shape:
        """Read an STL file and return its shape."""
        shape = TopoDS_Shape()
        reader = StlAPI_Reader()
        if not reader.Read(shape, stl_file):
            raise ValueError("Failed to read the STL file")
        return shape

    @staticmethod
    def _write_stl(shape: TopoDS_Shape, stl_file: str, linear_deflection=0.8, angular_deflection=0.6):
        """Write a shape to an STL file."""
        mesh = BRepMesh_IncrementalMesh(shape, linear_deflection, True, angular_deflection, True)
        mesh.Perform()

        writer = StlAPI_Writer()
        if not writer.Write(shape, stl_file):
            raise IOError(f"Failed to write STL file: {stl_file}")

    @staticmethod
    def _read_brep(brep_file: str) -> TopoDS_Shape:
        """Read a BREP file and return its shape."""
        shape = TopoDS_Shape()
        with open(brep_file, "r") as file:
            BRepTools.Read(shape, file)
        if shape.IsNull():
            raise ValueError("Failed to read the BREP file")
        return shape

    @staticmethod
    def _write_brep(shape: TopoDS_Shape, brep_file: str):
        """Write a shape to a BREP file."""
        with open(brep_file, "wb") as file:
            BRepTools.Write_s(shape, file)

    @staticmethod
    def _write_temp_stl(shape: TopoDS_Shape) -> str:
        """Write a temporary STL file for intermediate use."""
        temp_stl = "temp.stl"
        CADConverter._write_stl(shape, temp_stl)
        return temp_stl

    @staticmethod
    def _convert_stl_to_3mf(input_stl: str, output_3mf: str):
        """Convert STL to 3MF using lib3mf."""
        wrapper = Wrapper()
        model = wrapper.CreateModel()
        mesh_object = model.AddMeshObject()

        with open(input_stl, "r") as stl:
            vertices = []
            vertex_map = {}
            triangles = []
            current_triangle = []

            for line in stl:
                tokens = line.strip().split()
                if tokens[0] == "vertex":
                    vertex = tuple(map(float, tokens[1:]))
                    if vertex not in vertex_map:
                        vertex_array = (c_float * 3)(*vertex)
                        position = Position(vertex_array)
                        vertex_map[vertex] = len(vertices)
                        vertices.append(position)
                    current_triangle.append(vertex_map[vertex])
                elif tokens[0] == "endfacet":
                    if len(current_triangle) == 3:
                        triangle_array = (c_uint32 * 3)(*current_triangle)
                        triangle = Triangle(triangle_array)
                        triangles.append(triangle)
                    current_triangle = []

            for vertex in vertices:
                mesh_object.AddVertex(vertex)
            for triangle in triangles:
                mesh_object.AddTriangle(triangle)

        model.AddBuildItem(mesh_object, wrapper.GetIdentityTransform())
        writer = model.QueryWriter("3mf")
        writer.WriteToFile(output_3mf)

        logging.info(f"STL '{input_stl}' successfully converted to 3MF '{output_3mf}'.")
