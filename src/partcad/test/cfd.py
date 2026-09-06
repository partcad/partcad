#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .. import cae as pc_cae
from .cae_test import CaeTest


class CfdTest(CaeTest):
    """`pc test`'s fluid dynamics check: the part behaves under the flow it sees.

    Applicable to a part that declares a `cfd:` section, and to nothing else -
    see `CaeTest` for why that gate is the whole design.
    """

    def __init__(self) -> None:
        super().__init__(pc_cae.CFD)
