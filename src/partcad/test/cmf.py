#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Whether what is to be made has its colour, material and finish specified (docs/design/cmf.md).

A part to be made - manufacturable, and not bought - has to have every solid in
a material and every face in a colour, each a CMF declaration that claims it
can be had ('manufacturable: true'). A material's claim to a colour counts for
the faces of a part made of it. A finish that is stated has to be a claim too;
none stated is as produced.

An assembly that sets CMF itself - its own CMF parameters, a link's CMF
'params:', a 'properties: color:' - is drawing what it holds, not specifying it,
and is manufacturable only if it is bought whole: if it declares a 'vendor' and
an 'sku' of its own. A bought assembly is judged by its own CMF, and nothing
inside it is.

Introduced as a warning: what it finds is said and does not fail the run,
unless the object, or its package, says 'cmf: {require: true}'.
"""

from .. import cmf as pc_cmf
from ..assembly import Assembly
from ..sketch import Sketch
from .test import Test

# The key of an object's (or a package's) configuration of this check.
CONFIG_KEY = "cmf"


def _required(ctx, shape) -> bool:
    """Whether 'cmf: {require: true}' is set on the object or on its package."""
    project = ctx.get_project(shape.project_name) if ctx is not None else None
    for config in (getattr(shape, "config", None), getattr(project, "config_obj", None)):
        section = config.get(CONFIG_KEY) if isinstance(config, dict) else None
        if isinstance(section, dict) and section.get("require") is True:
            return True
    return False


def _purchasable(shape) -> bool:
    if isinstance(shape, Assembly):
        return shape.is_declared_purchasable()
    store = shape.get_store_data() if hasattr(shape, "get_store_data") else None
    return bool(store is not None and store.is_purchasable)


def claim_problems(ctx, kind: str, reference: str, relative_to: str):
    """What is wrong with 'reference' as a claim that this can be had: [] when nothing is."""
    if reference is None:
        return []
    rgba = pc_cmf.rgba_of_reference(reference)
    if rgba is not None:
        return ["the %s '%s' is display-only, a picture rather than a specification" % (kind, reference)]
    declaration = pc_cmf.lookup(ctx, kind, reference, relative_to, quiet=True)
    if declaration is None:
        return ["the %s '%s' does not resolve to a declaration" % (kind, reference)]
    if not declaration.manufacturable:
        return ["the %s '%s' is display-only (manufacturable: false)" % (kind, reference)]
    return []


def part_findings(ctx, shape) -> list:
    """What keeps a part's CMF from being specified, as sentences; [] when nothing does."""
    summary = pc_cmf.summary_of(shape)
    findings = []
    if not summary:
        return ["it states no colour and no material"]
    unspecified = summary.get("unspecified") or {}
    for component, what, things in (("color", "colour", "face"), ("material", "material", "solid")):
        count = unspecified.get(component)
        if not count:
            continue
        if count == "all":
            findings.append("no %s on any %s" % (what, things))
        elif count == "some":
            findings.append("no %s on some %ss" % (what, things))
        else:
            findings.append("no %s on %d %s(s)" % (what, count, things))
    seen = set()
    for cmf_set in summary.get("sets") or []:
        for kind in pc_cmf.KINDS:
            reference = cmf_set.get(kind)
            if reference is None or (kind, reference) in seen:
                continue
            seen.add((kind, reference))
            findings.extend(claim_problems(ctx, kind, reference, shape.project_name))
    return findings


def assembly_findings(ctx, shape) -> list:
    """What CMF an assembly sets itself, if it is not bought whole; [] otherwise."""
    if _purchasable(shape):
        findings = []
        for kind, reference in pc_cmf.own_parameters(shape, ctx).items():
            findings.extend(claim_problems(ctx, kind, reference, shape.project_name))
        return findings
    setters = pc_cmf.assembly_cmf_setters(shape, ctx)
    if not setters:
        return []
    return [
        "it sets CMF itself (%s), which draws what it holds rather than specifying it: an assembly that sets CMF "
        "is manufacturable only if it declares a 'vendor' and an 'sku' of its own. Declare the variants as parts "
        "(an 'enrich' that fixes 'color') and link those" % ", ".join(setters)
    ]


class CmfTest(Test):
    """Fail what is to be made without its colour, material and finish specified."""

    def __init__(self) -> None:
        super().__init__("cmf")

    def inapplicable(self, shape):
        if isinstance(shape, Sketch):
            return "a sketch is not made of anything"
        if not getattr(shape, "is_manufacturable", True):
            return "it is not to be made (manufacturable: false)"
        if not isinstance(shape, Assembly) and _purchasable(shape):
            return "it is bought, in whatever its vendor sells it in"
        return None

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        # Never remembered: the verdict turns on declarations the shape's key
        # does not cover - whether the colours it names claim to be had, in
        # whichever package declares them - and on 'cmf: {require:}', and what
        # it reads is the summary recorded with the build, which is cached
        # already. A warning remembered as a pass would also go unsaid.
        test_ctx[self.NOT_CACHEABLE] = True
        reason = self.inapplicable(shape)
        if reason is not None:
            return self.not_applicable(shape, reason)
        if isinstance(shape, Assembly):
            # One bought whole is judged by its own CMF alone, and needs none
            # of its children; any other is judged by its links too.
            if not _purchasable(shape):
                try:
                    await shape.do_instantiate()
                except Exception as e:
                    # Not a pass, as in 'connectivity': a check that fell over
                    # has nothing to say. 'cad' fails an assembly that will not
                    # instantiate in its own right.
                    return self.failed(shape, "the CMF check could not be run: %s" % e)
            findings = assembly_findings(ctx, shape)
        else:
            if await shape.get_wrapped(ctx) is None:
                return self.passed(shape, "the shape did not build; that is the 'cad' test's to report")
            findings = part_findings(ctx, shape)
        if not findings:
            return self.passed(shape)
        message = "CMF not specified: " + "; ".join(findings)
        if _required(ctx, shape):
            return self.failed(shape, message)
        return self.warned(shape, message + " (a warning until 'cmf: {require: true}')")
