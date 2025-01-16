from pathlib import Path
from OCP.TopoDS import TopoDS_Shape


class BaseConverter:
    def __init__(self, input_file: Path, output_file: Path):
        self.input_file = input_file
        self.output_file = output_file

    def read(self) -> TopoDS_Shape:
        """Read the input file and return a TopoDS_Shape."""
        raise NotImplementedError("This method must be implemented by subclasses.")

    def write(self, shape: TopoDS_Shape) -> None:
        """Write a TopoDS_Shape to the output file."""
        raise NotImplementedError("This method must be implemented by subclasses.")
