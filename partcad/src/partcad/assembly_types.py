from typing import Final
from partcad.types import Format, FormatGroup, FormatsMetaBase


class AssyType:
    ASSY: Final[Format] = Format("assy", "assy")


class ImportableAssemblyType:
    STEP: Final[Format] = Format("step", "step")
    

class AssemblyTypesMeta(FormatsMetaBase):
    """
    Single place to gather all sketch formats from different FormatGroups.
    """
    yaml_based: FormatGroup = FormatGroup(AssyType)
    importable: FormatGroup = FormatGroup(ImportableAssemblyType)

    def __init__(self) -> None:
        super().__init__()


AssemblyTypes: Final[AssemblyTypesMeta] = AssemblyTypesMeta()
