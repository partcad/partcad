from typing import Callable, Dict

from .registry import _factory_registry
from . import (
    part_factory_step,
    part_factory_brep,
    part_factory_3mf,
    part_factory_ai_build123d,
    part_factory_ai_cadquery,
    part_factory_ai_openscad,
    part_factory_alias,
    part_factory_build123d,
    part_factory_cadquery,
    part_factory_enrich,
    part_factory_extrude,
    part_factory_kicad,
    part_factory_obj,
    part_factory_scad,
    part_factory_stl,
    part_factory_sweep,
)


def get_factory(format_type: str) -> Callable:
    return _factory_registry.get(format_type)


__all__ = ["get_factory"]
