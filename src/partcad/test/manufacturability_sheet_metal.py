#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Is this sheet metal part one a brake could actually produce?

A sheet metal part is not described the way the other manufactured parts are. It
is not made from stock: it is made from a *flat piece*, which somebody else made
and which already carries the outline and the holes, and the whole of what the
sheet metal process contributes is the bends. So the declaration names two
things - the part that goes in ('source') and the sketch that says where the
bends are ('instructions') - and they are what this checks.

Two questions, and each of them is about one of those:

* The blank has to be flat, top and bottom. What goes into a brake is a piece of
  sheet, so the horizontal plane through its highest point and the one through
  its lowest each meet it in an area rather than touching it at a point. A part
  that fails this is not a blank - most often it is the bent part itself, named
  by mistake.
* Every bend has to say what it is. Two identical lines on a drawing are a bend
  up through 90 degrees and a bend down through 30, and nothing about the lines
  says which; so each of them carries an angle, an inner radius and a direction,
  and a line that carries none of that is a bend nobody can make.

What this does not check is the geometry of the part itself against those
instructions. Whether the bends produce the shape the part declares is a
question for the day PartCAD bends the blank itself; until then the part is what
its own type built, and these are the manufacturing inputs beside it.
"""

import hashlib
import math

from .. import logging as pc_logging
from ..part import Part
from ..part_config import PartConfiguration
from ..part_config_manufacturing import METHOD_SHEET_METAL
from .manufacturability_reference import resolve_reference
from .test import Test

# The annotation keys a bend line has to carry, and what each has to be.
#
# Read case-insensitively and off the sketch rather than off a file: a DXF
# states them as XDATA and that is where they come from today, but what this
# reads is 'Sketch.get_annotations()', so a sketch type that learns to state the
# same thing needs no change here.
KEY_ANGLE = "angle"
KEY_RADIUS = "radius"
KEY_DIRECTION = "direction"

# Which way the metal goes, as the drawing may spell it. Case-insensitive
# because a layer called 'BEND_UP' and an annotation of 'up' are the same word
# written by two different people.
DIRECTIONS = ("up", "down")

# The DXF entity types a bend is drawn as. A bend line is a line: an arc or a
# circle on a bend layer is something else - a hole, a relief, a note - and is
# not held to the three keys above.
BEND_TYPES = ("LINE",)


def _number(value):
    """A metadata value read as a number, or None if it is not one.

    XDATA states a value either as a real or as the text of one, so both arrive
    here. A boolean is refused before 'float()' sees it, for the reason
    'shape_config.is_a_length' gives: by then it is an ordinary 1.0 and nothing
    can tell it from a number somebody wrote.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _absent_or_not_a_number(metadata: dict, key: str) -> str:
    """Why a numeric annotation could not be read: it is missing, or it is text."""
    if key not in metadata:
        return "no '%s'" % key
    return "a non-numeric '%s' (%r)" % (key, metadata[key])


def bend_failure(annotation: dict) -> str | None:
    """Why this bend cannot be made, or None if it can.

    The three keys, and the one thing each of them has to be:

    * 'angle' - how far the metal is turned, in degrees, and a bend turns it
      somewhere: zero is not a bend, and a negative angle is a direction written
      twice (there is a key for that).
    * 'radius' - the *inner* radius of the bend, in millimetres. Zero is a fold,
      which no brake produces and no metal survives, so it has to be stated and
      it has to be more than nothing.
    * 'direction' - 'up' or 'down', in either case.
    """
    metadata = annotation.get("metadata") or {}
    if not metadata:
        return "it carries no metadata"

    failures = []

    angle = _number(metadata.get(KEY_ANGLE))
    if angle is None:
        failures.append(_absent_or_not_a_number(metadata, KEY_ANGLE))
    elif angle <= 0.0:
        failures.append("an '%s' of %g, which is not a bend" % (KEY_ANGLE, angle))
    elif angle >= 360.0:
        # Not a bound on what a brake can do - that is the metal's business and
        # nothing here knows the metal - but on what the number can be saying:
        # a whole turn and more is not an angle anything was turned through, and
        # is how a value in some other unit reads when it is taken for degrees.
        failures.append("an '%s' of %g degrees, which is a whole turn or more" % (KEY_ANGLE, angle))

    radius = _number(metadata.get(KEY_RADIUS))
    if radius is None:
        failures.append(_absent_or_not_a_number(metadata, KEY_RADIUS))
    elif radius <= 0.0:
        failures.append("a '%s' of %g, which is a fold rather than a bend" % (KEY_RADIUS, radius))

    direction = metadata.get(KEY_DIRECTION)
    if direction is None:
        failures.append("no '%s'" % KEY_DIRECTION)
    elif not isinstance(direction, str) or direction.strip().lower() not in DIRECTIONS:
        failures.append("a '%s' of %r, which is neither 'up' nor 'down'" % (KEY_DIRECTION, direction))

    if not failures:
        return None
    return "it has " + ", ".join(failures)


def _describe(annotation: dict) -> str:
    """How to name one element of the drawing when reporting it."""
    handle = annotation.get("handle")
    layer = annotation.get("layer")
    described = annotation.get("type") or "element"
    if layer:
        described += " on layer '%s'" % layer
    if handle:
        described += " (#%s)" % handle
    return described


class ManufacturabilitySheetMetalTest(Test):
    def __init__(self) -> None:
        super().__init__("manufacturability-sheet-metal")

    async def cache_key_suffix(self, ctx, shape) -> str:
        """What this test reads beyond the part itself, folded into the cache key.

        Everything it reads is somewhere else. The part's own hash covers what
        the part is built from, and 'manufacturing:' is not that - it is one of
        the keys a shape's key deliberately leaves out ('_NON_GEOMETRIC_CONFIG_KEYS'
        in shape.py), because naming a blank does not change the geometry of the
        part that names it. So without this, correcting a mistyped reference -
        or editing the bend angles in the drawing the reference points at -
        would be answered with the cached verdict of the declaration that was
        replaced, which is the one thing a test must never do.

        Two things go in for each of the two references: the reference as
        written, which is what changes when the part is re-pointed, and the
        cache key of what it resolves to, which is what changes when that object
        does. The second is the whole reason this is asynchronous: a shape has
        no correct key until the files it is built from are on disk, which is
        what 'get_cache_key_async()' waits for.

        An object that cannot be resolved, or that is not cached in its own
        right, contributes its reference and an empty key. That is a verdict
        this test is about to fail anyway, and failing it is cheaper than
        deciding here what an unresolvable reference should key as.

        Asked of parts only, exactly as 'test()' below is. An assembly's
        'manufacturing:' is a different vocabulary in the same spelling - every
        'type: assy' assembly is given 'method: assy' by AssemblyConfiguration -
        and reading one with 'PartConfiguration.get_manufacturing_data' reports
        the assembly's own method as an unknown *part* method. That is an error
        rather than a warning, so it does not merely read oddly: it fails
        'pc test' for every package that contains an assembly.
        """
        if not isinstance(shape, Part):
            return ""

        manufacturing_data = PartConfiguration.get_manufacturing_data(shape)
        if manufacturing_data.method != METHOD_SHEET_METAL:
            # Nothing is read, so nothing is added: a part made some other way
            # keys exactly as it always has, and the cache entries it already
            # has stay valid.
            return ""

        declared = []
        for kind, reference in (
            ("part", manufacturing_data.source),
            ("sketch", manufacturing_data.instructions),
        ):
            if not reference:
                declared.append("%s@" % kind)
                continue
            object = await self._resolve(ctx, shape, reference, kind)
            key = None
            if object is not None:
                try:
                    key = await object.get_cache_key_async()
                except Exception as e:  # pylint: disable=broad-except
                    pc_logging.debug("Failed to key '%s' for the sheet metal test: %s" % (reference, e))
            declared.append("%s:%s@%s" % (kind, reference, key or ""))
        return ".sheet-metal=" + hashlib.sha256(";".join(declared).encode()).hexdigest()[:16]

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        if not isinstance(shape, Part):
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        manufacturing_data = PartConfiguration.get_manufacturing_data(shape)
        if manufacturing_data.method != METHOD_SHEET_METAL:
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        missing = manufacturing_data.missing_fields()
        if missing:
            return self.failed(
                shape,
                "The sheet metal declaration states no %s" % " and no ".join("'%s'" % field for field in missing),
            )

        failed = False
        # Both questions are asked, even when the first of them fails: a package
        # that got the blank and the bend lines wrong should learn both in one
        # run, which is the rule the rest of the manufacturability checks follow.
        if not await self.blank_is_flat(ctx, shape, manufacturing_data.source):
            failed = True
        if not await self.bends_are_stated(ctx, shape, manufacturing_data.instructions):
            failed = True

        if failed:
            return self.TEST_FAILED
        return self.passed(shape)

    async def _resolve(self, ctx, shape, reference: str, kind: str):
        """The object a 'manufacturing:' reference names, or None.

        The rule is shared with the other checks that read another object; see
        'manufacturability_reference.resolve_reference', which is where it
        lives and why.
        """
        return await resolve_reference(ctx, shape, reference, kind)

    async def blank_is_flat(self, ctx, shape, reference: str) -> bool:
        """Whether what goes into the brake is a flat piece of sheet.

        Asked of the part named by 'source', not of the part under test: the one
        under test is the bent result, and a bent part is not flat - that is
        what bending it did.
        """
        source = await self._resolve(ctx, shape, reference, "part")
        if source is None:
            return self.failed(shape, "The sheet metal source part '%s' is not found", reference)

        envelope = await source.get_wrapped(ctx)
        if envelope is None:
            return self.failed(shape, "Failed to get the shape of the sheet metal source part '%s'", reference)

        from .manufacturability_analysis import flatness

        measured = await flatness(ctx, envelope)
        # Zero area means the plane through that extreme touches the shape
        # rather than meeting it, which is what "not flat on that side" is.
        not_flat = [side for side, key in (("bottom", "area_min"), ("top", "area_max")) if not measured.get(key)]
        if not_flat:
            return self.failed(
                shape,
                "The sheet metal source part '%s' is not flat on the %s",
                reference,
                " or the ".join(not_flat),
            )
        return self.TEST_PASSED

    async def bends_are_stated(self, ctx, shape, reference: str) -> bool:
        """Whether every bend the instructions draw says what kind of bend it is.

        Every failure is reported rather than only the first, for the reason
        'ManufacturabilityTest.software_failure' gives: a drawing that left the angle off two
        lines should say so about both in one run.
        """
        instructions = await self._resolve(ctx, shape, reference, "sketch")
        if instructions is None:
            return self.failed(shape, "The sheet metal instructions sketch '%s' is not found", reference)

        annotations = await instructions.get_annotations(ctx)
        bends = [a for a in annotations if a.get("type") in BEND_TYPES]
        if not bends:
            # Either the sketch states nothing about its elements at all - which
            # is every sketch type but 'dxf' today - or the layers this
            # reference selected hold no lines. Both leave nothing to bend
            # along, and a part bent along nothing is not a part this can pass.
            return self.failed(
                shape,
                "The sheet metal instructions sketch '%s' draws no bend lines",
                reference,
            )

        failed = False
        for annotation in bends:
            failure = bend_failure(annotation)
            if failure:
                self.failed(
                    shape,
                    "The bend drawn by the %s of '%s' cannot be made: %s",
                    _describe(annotation),
                    reference,
                    failure,
                )
                failed = True
        if failed:
            return self.TEST_FAILED
        return self.TEST_PASSED
