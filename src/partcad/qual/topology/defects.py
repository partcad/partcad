#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'defects' check: the faces and edges of a part that are badly made, and where they are.

Two basic checks say something about the whole of a part's geometry, in words:
'validity' that OCCT will not certify it, and 'degenerate' that it has no size to
it in some direction. Neither says where, because neither has a where: a solid
is certified or it is not, and a bounding box is flat or it is not. But what
makes a solid uncertifiable is nearly always some of its pieces, and so is most
of what makes a mesher or a CAM path fail on a part that is not flat at all. This
asks which pieces, and shows them:

- the faces and edges OCCT finds fault with on their own -- a wire that crosses
  itself, a curve that leaves its surface -- by OCCT's own name for the fault;
- the **free** edges of a solid: an edge that bounds one face only, which is a
  hole in its skin. What 'validity' says of an LDraw brick meshed from triangles
  is these, 224 of them, where the studs were never joined to the top;
- the **slivers**: an edge shorter than 'minLength', or a face narrower than it,
  which is 'degenerate''s question asked of each piece instead of the whole
  (with its threshold, a thousandth of a millimetre, unless the object says
  otherwise).

Reported, and not failed, for the reason 'validity' gives: the parts with most
of these are ones nothing is functionally wrong with, and a red build over them
would say something untrue. It is a finding with a place, which is what makes it
a topology check: the pieces are left behind as geometry (see
'partcad.qual.highlight'), and the IDE's Topology tab shows them on the part with
the rest faded.

Only pieces. A part every face of which is defective is shown nothing, because
showing all of it singles nothing out; the count and the words say it instead.
What OCCT finds wrong with a shell or a solid as a whole -- a shell that is not
closed -- belongs to no piece, and is said in words beside them.

Parameters, on the object:

    parts:
      bracket:
        qual:
          topology:
            defects:
              minLength: 0.01    # mm; shorter edges, and narrower faces, are slivers
"""

import json

from ... import sandbox_versions, shape_envelope
from ... import surface as pc_surface
from ... import wrapper
from ...assembly import Assembly
from ...process_crash import describe_exit_code
from ...sketch import Sketch
from .. import highlight
from ..qualification import Qualification, TopologyQualification

# The 'degenerate' check's threshold for a whole part, in millimetres, which is
# what a piece is held to unless the object says otherwise.
DEFAULT_MIN_LENGTH = 1e-3

# What each kind of fault is called where a person reads it.
_NAMES = {
    "free": "free (a hole in the skin)",
    "sliver": "a sliver",
}


def _plural(count: int, noun: str) -> str:
    return "%d %s%s" % (count, noun, "" if count == 1 else "s")


class DefectsTest(TopologyQualification):
    """Report the faces and edges of a part that are badly made, and show them."""

    WRAPPERS = ("solidity.py", "defects.py", "tolerance.py")

    def __init__(self) -> None:
        super().__init__("defects")

    def inapplicable(self, shape):
        if isinstance(shape, Sketch):
            return "a sketch is not a body"
        if isinstance(shape, Assembly):
            return "an assembly is checked through its parts, each of which is tested in its own right"
        # A wall is a skin by its type, every edge of which is free on purpose.
        return pc_surface.not_a_body(shape)

    def _min_length(self, shape) -> float:
        value = self.params(shape).get("minLength", DEFAULT_MIN_LENGTH)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            return DEFAULT_MIN_LENGTH
        return float(value)

    async def cache_key_suffix(self, ctx, shape) -> str:
        """The parameter, which the shape's hash does not cover."""
        if self.inapplicable(shape) is not None:
            return ""
        return ".defects=%s" % json.dumps(self._min_length(shape))

    async def restore_artifact_async(self, ctx, shape, artifact: dict) -> bool:
        return await highlight.restore_async(ctx, artifact)

    async def test(self, tests_to_run: list[Qualification], ctx, shape, test_ctx: dict = None) -> bool:
        if test_ctx is None:
            test_ctx = {}
        reason = self.inapplicable(shape)
        if reason is not None:
            return self.not_applicable(shape, reason)

        try:
            solidity = await shape.get_solidity_async(ctx)
            envelope = await shape.get_wrapped(ctx) if solidity is not None else None
        except Exception as e:  # pylint: disable=broad-except
            # A part that will not build is 'cad''s to report.
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "Failed to build: %s" % e)
            return self.TEST_PASSED
        if solidity is None or envelope is None:
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "The shape did not build; that is the 'cad' test's to report")
            return self.TEST_PASSED
        if not solidity.get("solids"):
            # Every edge of a skin is free. Whether a part should be one is 'shell''s question.
            return self.not_applicable(shape, "it holds no solid, which 'shell' reports")

        min_length = self._min_length(shape)
        try:
            found = await self._find(ctx, envelope, min_length)
        except Exception as e:  # pylint: disable=broad-except
            # Reaching here means this check broke rather than that the shape
            # is sound; like 'validity', it is said rather than failed.
            test_ctx[self.NOT_CACHEABLE] = True
            self.info(shape, "could not be checked: %s" % e)
            return self.TEST_PASSED

        faces = int(found.get("defective_faces") or 0)
        edges = int(found.get("defective_edges") or 0)
        whole = [str(name) for name in found.get("whole") or []]
        if faces == 0 and edges == 0:
            if whole:
                return self.passed(
                    shape,
                    "no face or edge is defective on its own; what OCCT finds wrong is with %s as a whole (%s), "
                    "which 'validity' reports" % ("its shells", ", ".join(whole)),
                )
            return self.passed(
                shape,
                "every one of its %d faces and %d edges is well formed, and none is thinner than %g mm"
                % (int(found.get("faces") or 0), int(found.get("edges") or 0), min_length),
            )

        sentence = self._sentence(found, min_length)
        pieces = [piece for piece in found.get("pieces") or [] if isinstance(piece, dict)]
        # What is left undrawn because it is all of the part is what the wrapper
        # says is ('whole_faces', 'whole_edges'), and nothing else: an edge that
        # could not be drawn is not every edge, and saying "all of it" of one
        # sliver among two thousand edges was wrong.
        whole_faces = bool(found.get("whole_faces"))
        whole_edges = bool(found.get("whole_edges"))
        if (faces == 0 or whole_faces) and (edges == 0 or whole_edges):
            sentence += " -- that is all of it, so there is nothing in particular to point at"
        elif not pieces:
            sentence += " -- none of them could be drawn, so this is all there is to see of them"
        elif whole_faces or whole_edges:
            sentence += " -- every %s is, which is all of it and is not drawn" % ("face" if whole_faces else "edge")
        verdict = self.warned(shape, "%s", sentence)

        geometry = []
        for piece in pieces:
            payload = piece.get("shape")
            if isinstance(payload, dict) and payload.get(shape_envelope.KEY_BREP):
                kind = "edge" if piece.get("kind") == "edge" else "face"
                geometry.append(
                    {
                        "name": kind + "s",
                        "kind": kind,
                        "brep": shape_envelope.brep_plain(payload.get(shape_envelope.KEY_BREP)),
                        "desc": "The defective %ss of '%s'" % (kind, shape.name),
                    }
                )
        if geometry:
            counted = [_plural(count, noun) for count, noun in ((faces, "face"), (edges, "edge")) if count]
            artifact = await highlight.make_async(
                ctx,
                shape,
                self.name,
                "%s defective" % " and ".join(counted),
                "'%s', with its defective faces and edges drawn in the colour of a finding" % shape.name,
                geometry,
                features=[
                    {
                        "at": item.get("center"),
                        "label": "%s %d: %s"
                        % (
                            item.get("kind", "face"),
                            int(item.get("index") or 0),
                            ", ".join(_NAMES.get(name, name) for name in item.get("problems") or []),
                        ),
                    }
                    for item in found.get("described") or []
                ],
            )
            if artifact is not None:
                self.artifact(shape, artifact)
        return verdict

    def _sentence(self, found: dict, min_length: float) -> str:
        """What was found, in one sentence: how many of what, and why."""
        faces = int(found.get("defective_faces") or 0)
        edges = int(found.get("defective_edges") or 0)
        counted = []
        if faces:
            counted.append("%d of its %d faces" % (faces, int(found.get("faces") or 0)))
        if edges:
            counted.append("%d of its %d edges" % (edges, int(found.get("edges") or 0)))
        causes = []
        free = int(found.get("free") or 0)
        if free:
            causes.append(
                "%s bound%s one face only, a hole in the skin" % (_plural(free, "edge"), "s" if free == 1 else "")
            )
        slivers = int(found.get("slivers") or 0)
        if slivers:
            causes.append("%s thinner than %g mm" % (_plural(slivers, "sliver"), min_length))
        rejected = []
        for item in found.get("described") or []:
            for name in item.get("problems") or []:
                if name not in ("free", "sliver") and name not in rejected:
                    rejected.append(name)
        if rejected:
            causes.append("OCCT finds fault with the rest (%s)" % ", ".join(rejected))
        sentence = "%s %s defective" % (
            " and ".join(counted),
            "is" if len(counted) == 1 and faces + edges == 1 else "are",
        )
        if causes:
            sentence += ": " + "; ".join(causes)
        whole = [str(name) for name in found.get("whole") or []]
        if whole:
            sentence += "; and OCCT finds fault with its shells as a whole (%s)" % ", ".join(whole)
        return sentence

    async def _find(self, ctx, envelope, min_length: float) -> dict:
        runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
        await runtime.ensure_async(sandbox_versions.OCP)
        request = {"shape": envelope, "minLength": min_length}
        exitcode, response_serialized, errors = await runtime.run_async(
            [wrapper.get("defects.py"), "defects"], shape_envelope.serialize(request)
        )
        if exitcode != 0 and not errors:
            errors = "the defects check failed: %s" % describe_exit_code(exitcode)
        if errors:
            raise Exception(errors)
        result = shape_envelope.deserialize(response_serialized)
        if not result.get("success", False):
            raise Exception(result.get("exception") or "the defects check failed")
        return result
