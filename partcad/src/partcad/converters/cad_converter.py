from pathlib import Path
from .stl_converter import StlConverter
from .step_converter import StepConverter
from .. import logging
# Import other converters as needed


class CADConverter:
    CONVERTERS = {
        "step": StepConverter,
        "stl": StlConverter,
        # Add other formats as needed
    }

    @staticmethod
    def is_supported_format(file_format: str) -> bool:
        """Check if the file format is supported."""
        return file_format in CADConverter.CONVERTERS

    @staticmethod
    def convert(input_file: str, output_file: str, input_format: str, output_format: str) -> None:
        """Convert a file from one CAD format to another."""
        if input_format not in CADConverter.CONVERTERS:
            raise ValueError(f"Unsupported input format: {input_format}")
        if output_format not in CADConverter.CONVERTERS:
            raise ValueError(f"Unsupported output format: {output_format}")

        input_converter = CADConverter.CONVERTERS[input_format](Path(input_file), Path(output_file))
        output_converter = CADConverter.CONVERTERS[output_format](Path(input_file), Path(output_file))

        shape = input_converter.read()
        logging.info(f"Shape type: {type(shape)}")
        output_converter.write(shape)
