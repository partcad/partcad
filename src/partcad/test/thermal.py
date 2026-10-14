#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .. import cae as pc_cae
from .cae import CaeTest


class ThermalTest(CaeTest):
    """`pc test`'s heat transfer check: the part stays as cool as it has to.

    Applicable to a part that declares a `thermal:` section, and to nothing else -
    see `CaeTest` for why that gate is the whole design.
    """

    def __init__(self) -> None:
        """Named "thermal", which is what `pc test -f thermal` filters on."""
        super().__init__(pc_cae.THERMAL)
