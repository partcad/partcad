from typing import Final
from partcad.types import Format, FormatGroup, FormatsMetaBase


class BasicSketchType:
    BASIC: Final[Format] = Format("basic", "basic")

class FileSketchType:
    DXF: Final[Format] = Format("dxf", "dxf")
    SVG: Final[Format] = Format("svg", "svg")

class ScriptSketchType:
    CADQUERY: Final[Format] = Format("cadquery", "py")
    BUILD123D: Final[Format] = Format("build123d", "py")

class SketchTypesMeta(FormatsMetaBase):
    """
    Single place to gather all sketch formats from different FormatGroups.
    """
    basic: FormatGroup = FormatGroup(BasicSketchType)
    file_based: FormatGroup = FormatGroup(FileSketchType)
    script_based: FormatGroup = FormatGroup(ScriptSketchType)
    

    def __init__(self) -> None:
        super().__init__()


SketchTypes: Final[SketchTypesMeta] = SketchTypesMeta()
