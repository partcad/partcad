#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import cadquery as cq

if __name__ != "__cqgi__":
    from cq_server.ui import ui, show_object

shape = cq.Workplane("front").circle(10.0).extrude(10.0)
show_object(shape)
