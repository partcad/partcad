#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import math
from typing import Sequence

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
    """A rigid body transform: a rotation about an axis through the origin followed by a translation.

    The accepted constructor forms are:
      Location()                                  the identity location
      Location(gp_Trsf)                           wrap an existing OCCT transformation
      Location(TopLoc_Location)                   wrap an existing OCCT location
      Location(Location)                          copy of another location
      Location([t, axis, angle])                  the packed form used by PartCAD config files,
                                                  e.g. [[0, 0, 0], [0, 0, 1], 0]
      Location(t, axis, angle)                    the same, spelled as three arguments
    """

    wrapped: TopLoc_Location

    def __init__(self, arg=None, axis=None, angle=None):
        if axis is not None or angle is not None:
            # The three-argument form: Location((x, y, z), (ax, ay, az), angle).
            if arg is None or axis is None or angle is None:
                raise ValueError("geom.Location: the three-argument form needs a translation, an axis and an angle")
            trsf = Location.trsf_from_coords(arg, axis, angle)
            self.wrapped = TopLoc_Location(trsf)
        elif arg is None:
            self.wrapped = TopLoc_Location()
        elif isinstance(arg, gp_Trsf):
            self.wrapped = TopLoc_Location(arg)
        elif isinstance(arg, TopLoc_Location):
            self.wrapped = arg
        elif isinstance(arg, Location):
            self.wrapped = arg.wrapped
        elif isinstance(arg, (list, tuple)):
            trsf = Location.trsf_from_coords(arg[0], arg[1], arg[2])
            self.wrapped = TopLoc_Location(trsf)
        else:
            raise ValueError("geom.Location: Invalid argument type")

    def inverse(self) -> "Location":
        """Return the location that undoes this one."""
        return Location(self.wrapped.Transformation().Inverted())

    def __mul__(self, other: "Location") -> "Location":
        """Compose two locations: (a * b) applies b first and then a."""
        if not isinstance(other, Location):
            return NotImplemented
        return Location(self.wrapped.Transformation().Multiplied(other.wrapped.Transformation()))

    def __repr__(self):
        trsf = self.wrapped.Transformation()
        trans = trsf.TranslationPart()
        quat = trsf.GetRotation()
        dir = gp_Vec()
        angle = quat.GetVectorAndAngle(dir)
        angle = 180.0 * angle[0] / math.pi
        return f"Location({[trans.X(), trans.Y(), trans.Z()]}, {[dir.X(), dir.Y(), dir.Z()]}, {angle})"

    @classmethod
    def trsf_from_coords(self, t: Sequence[float], ax: Sequence[float], angle: float):
        # pc_logging.info(f"trsf_from_coords: {t}, {ax}, {angle}")
        T = gp_Trsf()
        T.SetRotation(
            gp_Ax1(gp_Pnt(), gp_Dir(ax[0], ax[1], ax[2])),
            angle * math.pi / 180.0,
        )
        T.SetTranslationPart(gp_Vec(t[0], t[1], t[2]))
        return T
