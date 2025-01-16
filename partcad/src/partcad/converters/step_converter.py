from pathlib import Path
from OCP.TopoDS import TopoDS_Shape
from OCP.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from .base_converter import BaseConverter


class StepConverter(BaseConverter):
    def read(self) -> TopoDS_Shape:
        """Read a STEP file and return a TopoDS_Shape."""
        step_reader = STEPControl_Reader()
        status = step_reader.ReadFile(str(self.input_file))
        if status != 1:
            raise RuntimeError(f"Failed to read STEP file: {self.input_file}")
        step_reader.TransferRoot()
        return step_reader.Shape()

    def write(self, shape: TopoDS_Shape) -> None:
        """Write a TopoDS_Shape to a STEP file."""
        step_writer = STEPControl_Writer()
        step_writer.Transfer(shape, STEPControl_AsIs)
        status = step_writer.Write(str(self.output_file))
        if status != 1:
            raise RuntimeError(f"Failed to write STEP file: {self.output_file}")
