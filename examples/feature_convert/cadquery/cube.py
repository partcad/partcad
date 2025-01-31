#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import cadquery as cq

if __name__ != "__cqgi__":
    from cq_server.ui import ui, show_object

width = 10.0
length = 10.0
height = 10.0

shape = cq.Workplane("front").box(width, length, height)

show_object(shape)
