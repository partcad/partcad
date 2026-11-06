#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'wall' part type: the walls a room is laid out with, as a surface or as a solid.

Built for laying out a space rather than for making anything: a floor plan, an
apartment for sale, the room a machine is going to stand in. A wall is its
elevation - a rectangle as long and as high as it is, straight or bent along an
arc, with its doors and windows cut out by a sketch - and what it is depends on
its thickness:

  * **No thickness** (the default): the elevation itself, a sheet of faces seen
    from one side and not there from the other - so that a picture of a room
    taken from outside it looks through the near walls at the far ones, the
    way a plan or a dollhouse is drawn. Geometry only, for a picture.
  * **A thickness**: the solid the elevation is the face of, extruded straight
    back through the thickness from the side it is seen from. A physical wall,
    which a check measures, a simulation collides with and an export writes -
    and which is drawn, where it says 'visual:', as the surface of it (see
    'partcad.visual'). That is what '//builtin/building:wall' is: a solid,
    whose visual is the private surface beside it.

See 'wrappers/wrapper_wall.py' for the geometry and the frame it is built in.

    parts:
      living-room-north:
        type: wall
        manufacturable: false
        length: 4200          # mm along the base: along the arc, for an arc wall
        height: 2700          # mm
        radius: 0             # 0 is straight; + bends towards its front, - away
        openings: windows     # (optional) a sketch, drawn on the wall unrolled flat
        thickness: 100        # (optional) mm behind its face; 0, or none, is a surface

Each of the five may be a '%...%' expression over the part's parameters (see
'partcad.expr'), which is how '//builtin/building:wall' is one declaration that
builds every wall: 'wall;length=4200,height=2700'.

It is never manufactured, and has to say so, whatever its thickness: a
declaration that does not state 'manufacturable: false' - itself, or through its
package - is refused with a message saying what to add, rather than flipped
quietly. A wall lays out a space; whoever reads the package should read there
that it is not a product anybody makes.

Two more things set a wall with no thickness apart from every other part, and
both follow from it being a surface on purpose (see 'partcad.surface'):

  * It leaves the wrapper as it was built: not closed into a solid, and not
    reported for not being one.
  * It reports 'oneSided: true' among its properties - an output, like a
    colour, worked out from what it is wherever it is reached from (see
    'Shape._shape_properties') - which is how everything that draws it, the
    IDE's 3D view and '//builtin/render', knows to draw it from the front only.
    A drawing is made from the shape tree, which carries properties and not
    declarations. Its faces' normals say which side the front is.

A wall with a thickness is a body like any other part, and is held to being one.
"""

from . import config as pc_config
from . import expr
from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, telemetry, wrapper
from .part_factory import PartFactory
from .process_crash import describe_exit_code

# What a wall is built from, and what each reads back as when it is not
# declared. 'length' and 'height' have no default: a wall nobody gave a size to
# is a mistake, not a default-sized wall. No 'thickness' is a surface.
REQUIRED_FIELDS = ("length", "height")
OPTIONAL_FIELDS = {"radius": 0.0, "openings": "", "thickness": 0.0}


def thickness_of(config, where: str = "") -> float:
    """The thickness a wall's declaration resolves to, in millimetres: 0 for a surface.

    Over the declaration's own parameter values, the way the factory resolves
    it, so that 'partcad.surface' - which decides whether a wall is a surface
    from the declaration it resolves to, without building it - and the factory
    cannot come to different answers. A value that is not a number reads as
    no thickness here; the factory is what refuses it, with the reason.
    """
    if not isinstance(config, dict) or config.get("thickness") in (None, ""):
        return 0.0
    values = pc_config.parameter_values(config.get("parameters"))
    try:
        return float(expr.resolve(config["thickness"], values, where) or 0.0)
    except (TypeError, ValueError):
        return 0.0


class WallDeclarationError(Exception):
    """A 'wall' part declared in a way that cannot be built, said as its author would want to hear it."""


@telemetry.instrument()
class PartFactoryWall(PartFactory):
    WRAPPERS = ("wall.py",)

    PYTHON_SANDBOX_VERSION = sandbox_versions.DEFAULT_PYTHON_VERSION

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitWall", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)

            where = "%s:%s" % (target_project.name, config["name"])

            # Before anything is registered, so that a refusal is the
            # per-object failure an unknown type is (see
            # '_validate_object_type_parameters').
            if config.get("manufacturable", True):
                raise WallDeclarationError(
                    "%s: a wall lays out a space, and is not a thing anybody makes, and has to say so: "
                    "add 'manufacturable: false' to it, or to its package" % where
                )

            values = pc_config.parameter_values(config.get("parameters"))
            resolved = {}
            for field in REQUIRED_FIELDS:
                if config.get(field) is None:
                    raise WallDeclarationError("%s: a wall needs a '%s'" % (where, field))
                resolved[field] = expr.resolve(config[field], values, where)
            for field, default in OPTIONAL_FIELDS.items():
                value = config.get(field)
                resolved[field] = default if value is None else expr.resolve(value, values, where)

            try:
                self.length = float(resolved["length"])
                self.height = float(resolved["height"])
                self.radius = float(resolved["radius"] or 0.0)
                self.thickness = float(resolved["thickness"] or 0.0)
            except (TypeError, ValueError) as e:
                raise WallDeclarationError(
                    "%s: 'length', 'height', 'radius' and 'thickness' are numbers of millimetres: %s" % (where, e)
                )
            if self.thickness < 0.0:
                raise WallDeclarationError(
                    "%s: 'thickness' is how far the wall goes back from its face, and is not %s"
                    % (where, self.thickness)
                )

            # The sketch the openings are cut out by, resolved as an extrusion
            # resolves the sketch it extrudes: a bare name in the package that
            # declared the wall, and a ':' path wherever it says. A wall in
            # '//builtin/building' is that package's, so a sketch handed to it
            # has to be named in full.
            openings = resolved["openings"]
            self.openings_spec = None
            if openings not in (None, ""):
                openings = str(openings)
                if ":" in openings:
                    project_name, sketch_name = source_project.resolve(openings)
                else:
                    project_name, sketch_name = source_project.name, openings
                self.openings_spec = "%s:%s" % (project_name, sketch_name)

            self._create(config)
            # What is built, as numbers: the declaration may say it in
            # expressions, and two of them that come to the same wall are the
            # same wall. The sketch's name too, and its content once it is
            # resolved (see 'prepare_async'). The thickness only where there is
            # one, so that a surface keeps the key it had before walls had any.
            built = {
                "length": self.length,
                "height": self.height,
                "radius": self.radius,
                "openings": self.openings_spec,
            }
            if self.thickness > 0.0:
                built["thickness"] = self.thickness
            self.part.hash.add_dict({"wall": built})
            if self.openings_spec is not None:
                self.part.cache_dependencies_broken = True

    def info(self, part):
        """The wall's dimensions as they were resolved, beside the usual shape info."""
        info: dict = super().info(part)
        info["Wall"] = {
            "length": self.length,
            "height": self.height,
            "radius": self.radius,
            "openings": self.openings_spec,
            "thickness": self.thickness,
        }
        return info

    async def prepare_async(self, part) -> None:
        """Resolve the openings sketch, and key this wall on what it contains.

        The name is in the key already; the content is not, and an edited
        sketch would otherwise go on being cut out of the wall it used to be.
        """
        if self.openings_spec is None:
            return
        sketch = self.ctx.get_sketch(self.openings_spec, referrer=self.project.name)
        if sketch is None:
            # Reported by 'instantiate', which is where it is worth saying.
            return
        if await part.add_cache_key_of(sketch):
            part.cache_dependencies_broken = False
        else:
            # A sketch with no key has content nothing here can vouch for.
            part.cacheable = False

    async def instantiate(self, part):
        with pc_logging.Action("Wall", part.project_name, part.name):
            try:
                openings = None
                if self.openings_spec is not None:
                    sketch = self.ctx.get_sketch(self.openings_spec, referrer=self.project.name)
                    if sketch is None:
                        part.error(
                            "%s:%s: the openings sketch '%s' is not found"
                            % (part.project_name, part.name, self.openings_spec)
                        )
                        return None
                    openings = await sketch.get_wrapped(self.ctx)
                    if openings is None:
                        part.error(
                            "%s:%s: the openings sketch '%s' produced no shape"
                            % (part.project_name, part.name, self.openings_spec)
                        )
                        return None

                runtime = self.ctx.get_python_runtime(version=self.PYTHON_SANDBOX_VERSION)
                await runtime.ensure_async(sandbox_versions.OCP)

                request = {
                    "length": self.length,
                    "height": self.height,
                    "radius": self.radius,
                    "thickness": self.thickness,
                    "openingsName": self.openings_spec or "",
                    "name": "%s:%s" % (part.project_name, part.name),
                    "label": part.name,
                    # Moved by the wrapper while the shape is live, and, for a
                    # wall with a thickness, validated like any solid; for a
                    # surface, nothing else (see 'Shape.finish_request').
                    shape_envelope.KEY_FINISH: part.finish_request(),
                }
                if openings is not None:
                    request["openings"] = openings
                exitcode, response_serialized, errors = await runtime.run_async(
                    [wrapper.get("wall.py"), "wall"], shape_envelope.serialize(request)
                )
                if exitcode != 0 and not errors:
                    errors = "%s:%s: the wall failed: %s" % (part.project_name, part.name, describe_exit_code(exitcode))
                if errors:
                    pc_logging.error(errors)
                    raise Exception(errors)

                result = shape_envelope.deserialize(response_serialized)
                if not result["success"]:
                    part.error("%s:%s: %s" % (part.project_name, part.name, result["exception"]))
                    return None

                self.ctx.stats_parts_instantiated += 1
                return result["shape"]
            except Exception as e:
                part.error("%s:%s: failed to build the wall: %s" % (part.project_name, part.name, e))
                pc_logging.exception("Failed to build a wall: %s" % e)
                return None
