#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A routed part: a profile swept along the route an assembly places it by
(issue #975, design D1, D5, D6, D9).

The part is declared once, with its profile - a round section ('diameter',
hollow with 'innerDiameter') or a sketch - and the ports and interfaces of its
ends, in the end frame. Its geometry comes from where it is placed: an assembly
link with a 'route:' hands it the route as the parameter 'route', the canonical
JSON 'route_path.canonical_json' writes, and each different route is a part of
its own, cached by that route.

Fetched without a route - to resolve its ends before the route exists, or on its
own - the part has its ports and its declaration, and no geometry: building it is
an error that says where a route comes from.
"""

import json
import math
import re

from . import logging as pc_logging
from . import route_path, sandbox_versions, shape_envelope, wrapper
from .part_factory import PartFactory
from .part_factory_sketch_profile import SketchProfile
from .process_crash import describe_exit_code

# The parameter a route arrives in (D5). Accepted by this type without being
# declared, the way a type's own parameters are (see
# 'PartFactory.ACCEPTED_OBJECT_TYPE_PARAMETERS'), and not policed: any other type
# may have a parameter of that name, as a script part that takes a route does.
ROUTE_PARAMETER = "route"

# A '%...%' expression that reads the route: ports and interfaces cannot, since
# the ends they define are resolved before the route exists.
_READS_ROUTE = re.compile(r"%[^%]*\b" + ROUTE_PARAMETER + r"\b[^%]*%")


class RoutedPartError(ValueError):
    """A routed part's declaration that cannot be used."""


def _reads_route(value) -> bool:
    if isinstance(value, str):
        return bool(_READS_ROUTE.search(value))
    if isinstance(value, dict):
        return any(_reads_route(k) or _reads_route(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_reads_route(v) for v in value)
    return False


def route_of(config) -> str:
    """The route a routed part was given, or '' when it was given none."""
    parameters = config.get("parameters") or {}
    declared = parameters.get(ROUTE_PARAMETER)
    if isinstance(declared, dict):
        return declared.get("default") or ""
    return declared or ""


class PartFactoryRouted(SketchProfile, PartFactory):
    WRAPPERS = ("route.py",)

    PYTHON_SANDBOX_VERSION = sandbox_versions.DEFAULT_PYTHON_VERSION

    ACCEPTED_OBJECT_TYPE_PARAMETERS = {**PartFactory.ACCEPTED_OBJECT_TYPE_PARAMETERS, ROUTE_PARAMETER: ""}

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitRouted", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)
            self.diameter = config.get("diameter")
            self.inner_diameter = config.get("innerDiameter")
            self.length = config.get("length")
            self.min_bend_radius = config.get("minBendRadius")
            self._validate(config)
            self.route = route_of(config)

            self.source_sketch_spec = None
            if "sketch" in config:
                self.resolve_sketch(source_project, config)

            self._create(config)
            if self.source_sketch_spec is not None:
                # As a sweep keys on its sketch: the name now, the content once
                # 'prepare_async' has folded the sketch's own key in.
                self.part.hash.add_string(self.source_sketch_spec)
                self.part.cache_dependencies_broken = True

    def _validate(self, config) -> None:
        """What the schema cannot say about a routed part's declaration."""
        has_diameter = self.diameter is not None
        has_sketch = "sketch" in config
        if has_diameter == has_sketch:
            raise RoutedPartError(
                "%s: a routed part's profile is 'diameter' or 'sketch', exactly one of the two" % config["name"]
            )
        if self.inner_diameter is not None:
            if not has_diameter:
                raise RoutedPartError("%s: 'innerDiameter' is the bore of a 'diameter'" % config["name"])
            if not self.inner_diameter < self.diameter:
                raise RoutedPartError(
                    "%s: 'innerDiameter' (%g) must be smaller than 'diameter' (%g)"
                    % (config["name"], self.inner_diameter, self.diameter)
                )
        for field in ("ports", "implements"):
            if _reads_route(config.get(field)):
                raise RoutedPartError(
                    "%s: its '%s' read the '%s' parameter; the ends they define are resolved before the route "
                    "exists, so they cannot depend on it" % (config["name"], field, ROUTE_PARAMETER)
                )

    async def prepare_async(self, part) -> None:
        if self.source_sketch_spec is not None:
            await SketchProfile.prepare_async(self, part)

    async def _outer_radius(self, part):
        """How far the profile reaches from the path: half the diameter, or the
        farthest corner of the sketch's bounding box from its origin (D9)."""
        if self.diameter is not None:
            return self.diameter / 2.0
        box = await self.sketch.get_bounding_box_async(self.ctx)
        if box is None:
            return None
        x_min, y_min, _, x_max, y_max, _ = box
        return max(math.hypot(x, y) for x in (x_min, x_max) for y in (y_min, y_max))

    async def instantiate(self, part):
        with pc_logging.Action("Routed", part.project_name, part.name):
            try:
                if not self.route:
                    part.error(
                        "%s: %s: a routed part is built from the route an assembly places it by ('route:'), "
                        "and this one has none" % (part.project_name, part.name)
                    )
                    return None

                sketch_env = None
                if self.source_sketch_spec is not None:
                    sketch_env = await self.sketch_envelope(part)
                    if sketch_env is None:
                        return None

                # D9, before the sweep: the path has to have room for the profile.
                outer_radius = await self._outer_radius(part)
                if outer_radius is None:
                    part.error("%s: %s: the profile's size could not be measured" % (part.project_name, part.name))
                    return None
                _, refusals = route_path.check_route(route_path.stops_from_json(self.route), outer_radius)
                if refusals:
                    for refusal in refusals:
                        part.error("%s: %s: %s" % (part.project_name, part.name, refusal.message))
                    return None

                runtime = self.ctx.get_python_runtime(version=self.PYTHON_SANDBOX_VERSION)
                await runtime.ensure_async(sandbox_versions.OCP)
                request = {
                    "route": self.route,
                    "diameter": self.diameter,
                    "innerDiameter": self.inner_diameter,
                    "sketch": sketch_env,
                    "name": "%s:%s" % (part.project_name, part.name),
                    "label": part.name,
                    # Validated and moved by the wrapper, while the shape is live (see 'Shape.finish_request').
                    shape_envelope.KEY_FINISH: part.finish_request(),
                }
                exitcode, response_serialized, errors = await runtime.run_async(
                    [wrapper.get("route.py"), "route"], shape_envelope.serialize(request)
                )
                if exitcode != 0 and not errors:
                    errors = "%s: %s: route failed: %s" % (part.project_name, part.name, describe_exit_code(exitcode))
                if errors:
                    pc_logging.error(errors)
                    raise Exception(errors)

                result = shape_envelope.deserialize(response_serialized)
                if not result["success"]:
                    part.error("%s: %s: %s" % (part.project_name, part.name, result["exception"]))
                    return None

                self.ctx.stats_parts_instantiated += 1
                return result["shape"]
            except Exception as e:
                part.error("%s: %s: failed to build a routed part: %s" % (part.project_name, part.name, e))
                pc_logging.exception(f"Failed to build a routed part: {e}")
                return None

    def route_record(self) -> dict:
        """The route this part was given, parsed, or {} when it has none."""
        return json.loads(self.route) if self.route else {}
