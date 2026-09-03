#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .. import cae as pc_cae
from .cae_test import CaeTest


class FeaTest(CaeTest):
    """`pc test`'s finite element check: the part holds up under what it carries.

    Applicable to a part that declares a `fea:` section, and to nothing else -
    see `CaeTest` for why that gate is the whole design.
    """

    def __init__(self) -> None:
        super().__init__(pc_cae.FEA)
