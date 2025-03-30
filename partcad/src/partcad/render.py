#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-22
#
# Licensed under Apache License, Version 2.0.
#

from typing import Any
from dataclasses import dataclass


# Merge render configs (to override project's config with the part's config)
def render_cfg_merge(a: dict, b: dict, path=[]):
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                a[key] = render_cfg_merge(a[key], b[key], path + [str(key)])
            if isinstance(a[key], list) and isinstance(b[key], list):
                a[key].extend(b[key])
            elif a[key] != b[key]:
                a[key] = b[key]
        else:
            a[key] = b[key]
    return a


DEFAULT_RENDER_WIDTH = 1024
DEFAULT_RENDER_HEIGHT = 1024

DEFAULT_RENDER_SVG_OPTS = {
    "width": DEFAULT_RENDER_WIDTH,
    "height": DEFAULT_RENDER_HEIGHT,
    "showAxes": False,
    "projectionDir": [1, -1, 0.75],
    "strokeWidth": 0.25,
    "strokeColor": [64, 192, 64],
    "hiddenColor": [32, 64, 32],
    "showHidden": False,
    # "marginLeft": 0,
    # "marginTop": 0,
}
