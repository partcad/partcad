#
# OpenVMP, 2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import math

from OCP.TopLoc import TopLoc_Location
from OCP.gp import (
    gp_Trsf,
    gp_Ax1,
    gp_Pnt,
    gp_Vec,
    gp_Dir,
)

from . import logging as pc_logging


class Location:
    wrapped: TopLoc_Location

    def __init__(self, arg=None):
        if arg is None:
            self.wrapped = TopLoc_Location()
        elif isinstance(arg, gp_Trsf):
            self.wrapped = TopLoc_Location(arg)
        elif isinstance(arg, list):
            trsf = Location.trsf_from_coords(arg[0], arg[1], arg[2])
            self.wrapped = TopLoc_Location(trsf)
        else:
            raise ValueError("geom.Location: Invalid argument type")

    def __repr__(self):
        trsf = self.wrapped.Transformation()
        trans = trsf.TranslationPart()
        quat = trsf.GetRotation()
        dir = gp_Vec()
        angle = quat.GetVectorAndAngle(dir)
        angle = 180.0 * angle[0] / math.pi
        return f"Location({[trans.X(), trans.Y(), trans.Z()]}, {[dir.X(), dir.Y(), dir.Z()]}, {angle})"

    @classmethod
    def trsf_from_coords(self, t: list[float], ax: list[float], angle: float):
        # pc_logging.info(f"trsf_from_coords: {t}, {ax}, {angle}")
        T = gp_Trsf()
        T.SetRotation(
            gp_Ax1(gp_Pnt(), gp_Dir(ax[0], ax[1], ax[2])),
            angle * math.pi / 180.0,
        )
        T.SetTranslationPart(gp_Vec(t[0], t[1], t[2]))
        return T
