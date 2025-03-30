#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.
#

import os

from partcad.part_types import PartTypes


TYPE_DEPENDENCIES = {
    PartTypes.SVG: ["cadquery-ocp==7.7.2", "ocpsvg==0.3.4", "build123d==0.8.0"],
    PartTypes.PNG: [
        "cadquery-ocp==7.7.2",
        "ocpsvg==0.3.4",
        "build123d==0.8.0",
        "svglib==1.5.1",
        "reportlab",
        "rlpycairo==0.3.0",
    ],
    PartTypes.STEP: ["cadquery-ocp==7.7.2"],
    PartTypes.BREP: ["cadquery-ocp==7.7.2"],
    PartTypes.STL: ["cadquery-ocp==7.7.2"],
    PartTypes.OBJ: ["cadquery-ocp==7.7.2"],
    PartTypes.THREEJS: ["cadquery-ocp==7.7.2"],
    PartTypes.GLTF: ["cadquery-ocp==7.7.2"],
    PartTypes.THREE_MF: ["cadquery-ocp==7.7.2", "cadquery==2.5.2"],
    PartTypes.BUILD123D: [
        "ocp-tessellate==3.0.9",
        "typing_extensions==4.12.2",
        "cadquery-ocp==7.7.2",
        "ocpsvg==0.3.4",
        "build123d==0.8.0",
    ],
    PartTypes.CADQUERY: [
        "cadquery==2.5.2",
        "cadquery-ocp==7.7.2",
        "ocp-tessellate==3.0.9",
        "ocpsvg==0.3.4",
        "nlopt==2.9.1",
        "numpy==2.2.1",
        "typing_extensions==4.12.2",
    ],
}


def get(filename):
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "wrappers",
        "load",
        "wrapper_" + filename,
    )


def get_render(filename):
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "wrappers",
        "render",
        "wrapper_render_" + filename,
    )
