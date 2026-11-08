#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'tolerance-surfaces' and 'tolerance-edges' checks: every feature of a part to be made says how precisely.

'manufacturability' asks whether a part that is made states a tolerance at all,
and passes one tolerated "feature by feature" -- a STEP file whose GD&T gives
several features tolerances of their own (see 'tolerance_inspect.reduce()'). It
does not ask *which* features, and a drawing that tolerances the bore and the
mounting face says nothing about the other forty faces of the part. These two
ask it of every face and every edge, and show the ones nothing covers.

A feature is covered:

- by the part's **general tolerance** -- its 'tolerance:' field, or the
  'tolerance' parameter of a type that takes one -- which is what a title block's
  "unless otherwise stated" is: it covers every feature at once, and a part that
  states one passes without anything being measured. 'general: false' among the
  check's parameters stops it counting, for a part every feature of which has to
  be toleranced on its own;
- by a dimension or a geometric tolerance of the STEP file the part is read
  from, that refers to it (see 'wrappers/wrapper_tolerance.py'). An edge is also
  covered when every face it bounds is.

The ones nothing covers are reported, counted and described, and left behind as
geometry to look at: the faces, and the edges as tubes along them, in a colour
that stands out on the part (see 'partcad.qual.highlight'). Which is what makes
these topology checks rather than basic ones.

Asked only of a **part that is to be made** -- one that says how it is made
('manufacturing:'), and does not say 'manufacturable: false'. A part that is
bought comes as it comes, and a part nobody makes needs no tolerance. Parameters,
on the object:

    parts:
      bracket:
        qual:
          topology:
            tolerance-surfaces:
              minArea: 1.0       # mm^2; smaller faces (fillets, chamfers) are not reported
            tolerance-edges:
              minLength: 0.5     # mm; shorter edges are not reported
              general: false     # a general tolerance does not cover the edges
"""

import json

from .. import procurement, sandbox_versions, shape_envelope
from .. import surface as pc_surface
from .. import wrapper
from ..part import Part
from ..process_crash import describe_exit_code
from ..qual import highlight
from ..qual.qualification import Test, TopologyQualification
from ..shape_config import is_a_length

FORCE_MANUFACTURING = "force_manufacturing"


def general_tolerance(part):
    """The tolerance the part states for every feature at once, or None when it states none.

    Its 'tolerance:' field, else the 'tolerance' parameter of a type that takes
    one -- but not what its file states, which is a tolerance of particular
    features and is what this check looks at one by one. 0.0 is "nobody said",
    and None too: neither covers anything.
    """
    declared = getattr(part, "_tolerance", None)
    if declared is None:
        getter = getattr(part, "get_object_type_parameter", None)
        declared = getter("tolerance") if getter is not None else None
    if not is_a_length(declared) or declared <= 0.0:
        return None
    return float(declared)


class _ToleranceTest(TopologyQualification):
    """What the two checks share: they differ in the kind of feature, its noun and its size."""

    WRAPPERS = ("tolerance.py",)

    # Set by the two subclasses.
    KIND = "face"
    NOUN = "face"
    MIN_SIZE = "minArea"
    UNIT = "mm^2"

    def inapplicable(self, shape):
        if not isinstance(shape, Part):
            return "only a part is made to a tolerance; an assembly's parts are each checked in their own right"
        if not shape.is_manufacturable:
            return "it says it is not manufacturable ('manufacturable: false')"
        if pc_surface.surface_type(shape) is not None:
            return "it is a surface by its type, and is never made"
        if not procurement.is_made(shape):
            if procurement.is_bought(shape):
                return "it is bought ('vendor:' and 'sku:'), and comes as it comes"
            return "it does not say how it is made ('manufacturing:'); 'manufacturability' reports that"
        return None

    def _parameters(self, shape) -> dict:
        params = self.params(shape)
        min_size = params.get(self.MIN_SIZE, 0.0)
        if not isinstance(min_size, (int, float)) or isinstance(min_size, bool) or min_size < 0:
            min_size = 0.0
        return {"minSize": float(min_size), "general": params.get("general", True) is not False}

    async def cache_key_suffix(self, ctx, shape) -> str:
        """The parameters, and what decides whether the check applies, neither of which the shape's hash covers."""
        if not isinstance(shape, Part):
            return ""
        made = procurement.is_made(shape)
        bought = procurement.is_bought(shape)
        return ".tolerance=%s" % json.dumps(
            [self._parameters(shape), made, bought, general_tolerance(shape)], sort_keys=True, default=str
        )

    async def test_cached(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        """The cached verdict -- except for a part reached through what it is made into.

        An assembly's manufacturability walks what it is made of with every
        check; whether each feature of a part is toleranced is the part's own
        question, answered where the part is tested, and must not make an
        assembly unmanufacturable through the cache (whose key does not carry
        the walk) in one run and not another.
        """
        if test_ctx.get(FORCE_MANUFACTURING):
            return self.TEST_PASSED
        return await super().test_cached(tests_to_run, ctx, shape, test_ctx)

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = None) -> bool:
        if test_ctx is None:
            test_ctx = {}
        reason = self.inapplicable(shape)
        if reason is not None:
            return self.not_applicable(shape, reason)
        if test_ctx.get(FORCE_MANUFACTURING):
            return self.TEST_PASSED

        parameters = self._parameters(shape)
        general = general_tolerance(shape)
        if general is not None and parameters["general"]:
            return self.passed(
                shape, "every %s is covered by the part's general tolerance of %g mm" % (self.NOUN, general)
            )

        try:
            envelope = await shape.get_wrapped(ctx)
        except Exception as e:  # pylint: disable=broad-except
            # A part that will not build is 'cad''s to report.
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "Failed to build: %s" % e)
            return self.TEST_PASSED
        if envelope is None:
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "The shape did not build; that is the 'cad' test's to report")
            return self.TEST_PASSED

        step = None
        if getattr(shape, "tolerance_file_format", None) == "step":
            step = getattr(shape, "path", None)
        try:
            measured = await self._measure(ctx, envelope, parameters["minSize"], step)
        except Exception as e:  # pylint: disable=broad-except
            test_ctx[self.NOT_CACHEABLE] = True
            return self.failed(shape, "the %ss could not be checked: %s" % (self.NOUN, e))

        missing = int(measured.get("untoleranced") or 0)
        total = int(measured.get("total") or 0)
        small = int(measured.get("smaller") or 0)
        if missing == 0:
            note = ""
            if small:
                note = "; %d smaller than %g %s not counted" % (small, parameters["minSize"], self.UNIT)
            return self.passed(
                shape,
                "every %s is toleranced by the file's GD&T (%d of %d)%s"
                % (self.NOUN, int(measured.get("toleranced") or 0), total, note),
            )

        if not measured.get("references"):
            if general is not None:
                cause = "its general tolerance is set not to count ('general: false') and its file tolerances none"
            elif step:
                cause = "the part states no general tolerance, and its STEP file tolerances no feature"
            else:
                cause = "the part states no general tolerance ('tolerance:'), and nothing else can tolerance one"
            sentence = "%s of its %d %ss has a tolerance: %s" % (
                "none" if missing + small == total else "%d" % missing,
                total,
                self.NOUN,
                cause,
            )
        else:
            sentence = "%d of its %d %ss %s no tolerance: the file's GD&T covers %d, and %s" % (
                missing,
                total,
                self.NOUN,
                "has" if missing == 1 else "have",
                int(measured.get("toleranced") or 0),
                (
                    "its general tolerance is set not to count ('general: false')"
                    if general is not None
                    else "there is no general tolerance"
                ),
            )
        largest = measured.get("described") or []
        if largest:
            first = largest[0]
            sentence += " (the largest is %s %d, a %s of %.3g %s)" % (
                self.NOUN,
                first.get("index", 0),
                str(first.get("type", self.NOUN)).replace("GeomAbs_", ""),
                float(first.get("size") or 0.0),
                self.UNIT,
            )
        if small:
            sentence += "; %d smaller than %g %s not counted" % (small, parameters["minSize"], self.UNIT)

        verdict = self.failed(shape, "%s", sentence)
        payload = measured.get("highlight")
        if isinstance(payload, dict) and payload.get(shape_envelope.KEY_BREP):
            artifact = await highlight.make_async(
                ctx,
                shape,
                self.name,
                "%d %s%s without a tolerance" % (missing, self.NOUN, "" if missing == 1 else "s"),
                "'%s', with the %ss nothing tolerances drawn in the colour of a finding" % (shape.name, self.NOUN),
                [
                    {
                        "name": self.NOUN + "s",
                        "kind": self.KIND,
                        "brep": shape_envelope.brep_plain(payload.get(shape_envelope.KEY_BREP)),
                        "desc": "The %ss of '%s' with no tolerance" % (self.NOUN, shape.name),
                    }
                ],
            )
            if artifact is not None:
                self.artifact(shape, artifact)
        return verdict

    async def restore_artifact_async(self, ctx, shape, artifact: dict) -> bool:
        return await highlight.restore_async(ctx, artifact)

    async def _measure(self, ctx, envelope, min_size: float, step) -> dict:
        runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
        await runtime.ensure_async(sandbox_versions.OCP)
        request = {"shape": envelope, "kind": self.KIND, "minSize": min_size}
        if step:
            request["step"] = step
        exitcode, response_serialized, errors = await runtime.run_async(
            [wrapper.get("tolerance.py"), "tolerance"], shape_envelope.serialize(request)
        )
        if exitcode != 0 and not errors:
            errors = "the tolerance check failed: %s" % describe_exit_code(exitcode)
        if errors:
            raise Exception(errors)
        result = shape_envelope.deserialize(response_serialized)
        if not result.get("success", False):
            raise Exception(result.get("exception") or "the tolerance check failed")
        return result


class ToleranceSurfacesTest(_ToleranceTest):
    """Fail a part to be made that has faces nothing tolerances, and show them."""

    KIND = "face"
    NOUN = "face"
    MIN_SIZE = "minArea"
    UNIT = "mm^2"

    def __init__(self) -> None:
        super().__init__("tolerance-surfaces")


class ToleranceEdgesTest(_ToleranceTest):
    """Fail a part to be made that has edges nothing tolerances, and show them."""

    KIND = "edge"
    NOUN = "edge"
    MIN_SIZE = "minLength"
    UNIT = "mm"

    def __init__(self) -> None:
        super().__init__("tolerance-edges")
