#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .. import cae as pc_cae
from .cae import CaeTest


class DynamicTest(CaeTest):
    """`pc test`'s dynamic check: the part does not ring where it must not.

    Applicable to a part that declares a `dynamic:` section, and to nothing else -
    see `CaeTest` for why that gate is the whole design.
    """

    def __init__(self) -> None:
        """Named "dynamic", which is what `pc test -f dynamic` filters on."""
        super().__init__(pc_cae.DYNAMIC)
