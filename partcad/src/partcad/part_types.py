from typing import Final

from partcad.types import Format, FormatGroup, FormatsMetaBase


class RenderType:
    SVG: Final[Format] = Format("svg", "svg")
    PNG: Final[Format] = Format("png", "png")


class ScriptType:
    SCAD: Final[Format] = Format("scad", "scad")
    CADQUERY: Final[Format] = Format("cadquery", "py")
    BUILD123D: Final[Format] = Format("build123d", "py")


class ModelType:
    STEP: Final[Format] = Format("step", "step")
    BREP: Final[Format] = Format("brep", "brep")
    STL: Final[Format] = Format("stl", "stl")
    OBJ: Final[Format] = Format("obj", "obj")
    THREE_MF: Final[Format] = Format("3mf", "3mf")


class CircuitBoardType:
    KICAD: Final[Format] = Format("kicad", "kicad_pcb")


class AiType:
    AI_CADQUERY: Final[Format] = Format("ai-cadquery", "py")
    AI_BUILD123D: Final[Format] = Format("ai-build123d", "py")
    AI_SCAD: Final[Format] = Format("ai-openscad", "scad")


class MetaType:
    ALIAS: Final[Format] = Format("alias", "")
    ENRICH: Final[Format] = Format("enrich", "")


class ExtraOps:
    EXTRUDE: Final[Format] = Format("extrude", "")
    SWEEP: Final[Format] = Format("sweep", "")


class ImportOnlyType:
    THREEJS: Final[Format] = Format("threejs", "json")
    GLTF: Final[Format] = Format("gltf", "json")


class PartTypesMeta(FormatsMetaBase):
    """
    Single place to gather all formats from different FormatGroups.
    """

    render: FormatGroup = FormatGroup(RenderType)
    inspectable: FormatGroup = FormatGroup(ModelType, ScriptType, MetaType, ExtraOps, CircuitBoardType)
    convert_input: FormatGroup = FormatGroup(ModelType, ScriptType, ImportOnlyType, MetaType)
    convert_output: FormatGroup = FormatGroup(ModelType)
    export: FormatGroup = FormatGroup(ModelType, ScriptType, RenderType)
    importable: FormatGroup = FormatGroup(ModelType, ScriptType, AiType)
    ai_generated: FormatGroup = FormatGroup(AiType)
    meta: FormatGroup = FormatGroup(MetaType)
    script: FormatGroup = FormatGroup(ScriptType)

    def __init__(self) -> None:
        super().__init__()


PartTypes: Final[PartTypesMeta] = PartTypesMeta()
# PartTypes.SWEEP = Format("sweep", "")
