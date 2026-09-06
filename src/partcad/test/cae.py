#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The shared body of the CAE checks `pc test` runs: FEA, and CFD.

A part passes when the analysis has **no findings**. That is the whole verdict,
and it is deliberately not a threshold PartCAD holds an opinion about: what
counts as too much stress or too much drag is the solver's judgement, expressed
by whether it says anything at all. PartCAD's part of the bargain is to run the
implementation the user configured and to report what it reported.

Two things bound how expensive this is, and both are the same gate:

* Only a **part** is analysed. An assembly is a set of parts that each carry
  their own boundary conditions, and a load on the whole of one says nothing
  about which member bears it.
* Only a part that **declares the section**. A `pc test -r` over a package tree
  would otherwise start a solver for every bolt in it, and a bolt with no
  `fea:` has nothing for a solver to be told. Declaring `fea:` is how a user
  says "check this one", which is why the check needs no flag of its own.

Everything else - which implementation, what the boundary conditions mean, what
units they are in - is `partcad.cae` and `Shape.analyze_async()`, shared with
`pc cae fea` so that the test and the command cannot disagree about a part.

Named after what it checks, like `cam.py` and `connect.py` beside it, and
emphatically *not* `cae_test.py`: that matches pytest's default `*_test.py`
pattern, so any collection that reaches `src/` imports this module as a test
file -- under a package name that does not resolve -- and the run dies during
collection rather than running anything.
"""

import hashlib
import json

from .. import cae as pc_cae
from .. import output
from ..part import Part
from .test import Test


class CaeTest(Test):
    def __init__(self, analysis: str) -> None:
        """One check per analysis, named after it: `pc test -f fea` selects it."""
        super().__init__(analysis)
        self.analysis = analysis

    def _config(self, shape):
        """The boundary conditions, or None when this test does not apply.

        A malformed section is *not* None: it is a failure, and it is raised
        rather than swallowed so that `test()` reports the sentence saying what
        is wrong with it.
        """
        if not isinstance(shape, Part):
            return None
        return pc_cae.config_of(shape, self.analysis)

    def cache_key_suffix(self, ctx, shape) -> str:
        """What this test reads beyond the shape, folded into the cache key.

        Three things, none of which moves `shape.hash`:

        * the boundary conditions, because a part whose load has just been
          doubled must not be answered with the verdict on the old one;
        * which implementation ran, because two solvers are two answers, and
          switching to one that is installed here is exactly what a user does
          after the first run;
        * the implementation's own configuration, because a package that
          re-tunes a solver's parameters has changed the question as surely as
          changing the load would.

        The last of those is the options as `analysis_getopts()` resolves them,
        which is the whole layering and not just the object's own `cae:`
        section: the implementing package's defaults are most of what a solver
        is told, and a package that re-tunes one of them would otherwise be
        answered with the verdict from before it did. They are read as the
        *declared* text and not as anything computed from running it -
        re-running the analysis to decide whether a cached answer may be used
        would cost precisely what the cache saves.
        """
        try:
            config = self._config(shape)
        except pc_cae.CaeConfigError as e:
            # A malformed section is its own cache key: correcting it has to
            # produce a fresh run rather than the failure of what it replaced.
            return ".malformed=" + hashlib.md5(str(e).encode()).hexdigest()
        if config is None:
            return ""

        parts = [json.dumps(config.to_data(), sort_keys=True)]
        try:
            options_project, format_name = shape._analysis_implementation(ctx, self.analysis, None)
            parts.append("%s:%s" % (options_project.name, format_name))
            opts, _output_dir = shape._output_getopts(
                ctx, format_name, output.CAE, ctx.get_project(shape.project_name), options_project
            )
            parts.append(json.dumps(opts, sort_keys=True, default=str))
        except Exception as e:
            # The implementation could not be resolved -- not installed, not a
            # dependency, misspelt. That is its own question and its own answer,
            # so it gets its own key rather than borrowing the one belonging to
            # a run that did resolve.
            parts.append("unresolved:%s" % e)
        return "." + self.analysis + "=" + hashlib.md5("\n".join(parts).encode()).hexdigest()

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        """Run the analysis, and pass the shape only if it found nothing.

        Three ways to fail, and they are different failures: the part declared
        the section wrongly, the implementation could not be run at all (no
        solver on this machine), or the analysis ran and reported something.
        Only the last is a verdict on the part, but none of them is a pass --
        a part that was asked about and not answered has not been checked.
        """
        try:
            config = self._config(shape)
        except pc_cae.CaeConfigError as e:
            # The part asked for this analysis and got the request wrong. That
            # is a failure of the package rather than of the part, and saying so
            # here is the only place a user finds out without running `pc cae`.
            return self.failed(shape, "%s", e)

        if config is None:
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        try:
            result = await shape.analyze_async(ctx, self.analysis)
        except pc_cae.CaeConfigError as e:
            return self.failed(shape, "%s", e)
        except Exception as e:
            # An implementation that could not run at all - not installed, no
            # solver on this machine, a crash. Not a verdict on the part, but
            # not something to pass over either: the part was asked about and
            # has not been answered.
            return self.failed(shape, "%s could not be run: %s", self.analysis.upper(), e)

        findings = result.get("findings") or []
        if findings:
            return self.failed(
                shape,
                "%s",
                pc_cae.findings_report("%s:%s" % (shape.project_name, shape.name), self.analysis, findings),
            )
        return self.passed(shape)
