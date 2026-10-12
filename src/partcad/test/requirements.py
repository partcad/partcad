#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .. import requirements
from .test import Test


class RequirementsTest(Test):
    """Check that the model is what the object's 'requirements:' say it has to be.

    The ports, the interfaces and the physical properties - the part of the
    requirements PartCAD can measure (see 'partcad.requirements', which is the
    whole of what each requirement means). A requirement on something PartCAD
    cannot find out fails rather than passes: "not known" is not "met". The
    features are prose and are not checked here, beyond a 'simulate:' entry
    naming a feature the requirements do not declare, which is a mistake in the
    declaration like any other.

    Never cached. What it reads is mostly not the geometry the cache key is
    made of - the requirements themselves, the ports and the interfaces, which
    can live in other packages, and the material a mass is worked out from -
    and asking again is a read of the declarations plus what the geometry's own
    cache entry already measured.
    """

    def __init__(self) -> None:
        super().__init__("requirements")

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        test_ctx[self.NOT_CACHEABLE] = True

        report = await requirements.check_async(ctx, shape)
        if not report.checks:
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        for check in report.checks:
            if check.passed is False:
                self.failed(shape, "%s: %s: %s: %s" % (check.section, check.name, check.requirement, check.detail))
            else:
                self.debug(shape, "%s: %s: %s: %s" % (check.section, check.name, check.requirement, check.detail))

        if report.failed:
            return self.TEST_FAILED
        return self.passed(shape, "%d requirements met" % len(report.checks))
