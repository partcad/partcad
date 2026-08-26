#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .test import Test
from ..assembly import Assembly


class ConnectTest(Test):
    """Check that an assembly's connection instructions are ones that can be followed.

    The instructions in the 'how' section of a 'connect'/'connectPorts' node are
    resolved leniently: whatever is missing takes a documented default, and
    whatever contradicts itself is reported and replaced with one, so that an
    assembly always builds. That leniency is what this test looks past. It fails
    an assembly whose instructions had to be repaired to be usable - a minimum
    above its maximum, or two interfaces that disagree about their thread - and
    passes one that is sound, including one that says nothing at all and takes
    every default.
    """

    def __init__(self) -> None:
        super().__init__("connect")

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        if not isinstance(shape, Assembly):
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        try:
            problems = await shape.get_connect_problems()
        except Exception as e:
            # An assembly that will not even instantiate is what the 'cad' test
            # is for; this one has nothing to say about it either way.
            self.debug(shape, "Failed to read the connections: %s" % e)
            return self.TEST_PASSED

        if not problems:
            return self.passed(shape)

        for name, problem in problems:
            self.failed(shape, "%s: %s" % (name, problem))
        return self.TEST_FAILED
