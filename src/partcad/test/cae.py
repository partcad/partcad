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
from .. import logging as pc_logging
from .. import output
from .. import runtime as pc_runtime
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
            # The part's own 'implementation:' if it declared one, exactly as
            # 'test()' resolves it -- otherwise the key describes the run the
            # user configuration would have produced rather than the run that
            # happens, and re-pointing a part at another solver would be
            # answered from the cache of the first.
            options_project, format_name = shape._analysis_implementation(
                ctx, self.analysis, declared=config.implementation
            )
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

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = None) -> bool:
        """Run the analysis, and pass the shape only if it found nothing.

        **There is one way to pass: the analysis ran and reported no findings.**
        Everything else is a failure, and the report says which of them it was.
        A part that declares `fea:` has asked a question, and any answer other
        than "nothing to report" is something a user has to act on:

        * the part declared the section wrongly;
        * the implementation could not be resolved -- not a dependency, did not
          load, declares no such file type;
        * the implementation resolved and could not run: no mesher, no solver,
          an unprovisionable sandbox, a crash;
        * the analysis ran and reported findings.

        **Not running is not a reason to skip.** A skip says the question does
        not apply here; a plugin that was asked to do something and did not do it
        has failed, and calling that a skip reports a part as checked when
        nothing checked it. That was this check's earlier behaviour -- a missing
        `ccx` warned and passed -- and it hid two things worth failing over: a
        CFD implementation that never converges, and a plugin that cannot be
        installed on this platform at all.

        **One thing is still a skip**, and it is the only one: the implementation
        declared a container and this machine has no container runtime. Nothing
        was asked, because the thing that asks could not start. That is not the
        implementation failing -- it may be perfectly good -- and PartCAD is the
        only party that can report it, since the implementation never runs. A
        plugin that brings its own dependencies is what makes this the only
        remaining excuse: everything else it needs, it carries.

        The consequence is real and is the point: declaring `fea:` in a shared
        package makes `pc test` fail for everyone who has not installed what the
        implementation needs. That is what declaring it means. A package that
        does not want the whole world running a solver should not declare the
        section, which is the same gate that keeps `pc test -r` from starting a
        solver for every bolt in a tree.

        What the failure must carry is *why*, because the reasons need different
        actions: install a solver, use another machine, or fix the part. The
        implementation is what knows which, so whatever it said is reported
        verbatim -- see `partcad.cae.dysfunction_report()`.
        """
        # Not `= {}` in the signature, the way the sibling checks have it: this
        # is the one that *writes* to `test_ctx` (`NOT_CACHEABLE`, below), and a
        # default argument is one dict shared by every call that omits one. A
        # direct call with no context would otherwise set the flag on the
        # default itself and leave it set for every later caller.
        if test_ctx is None:
            test_ctx = {}

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
            # Resolved here, and separately, so that failing to resolve it
            # reads differently from failing to run it. Both are failures now,
            # but they ask for different things: a name that resolves to nothing
            # is a configuration to correct, and a plugin that will not run is a
            # machine to equip or a platform to leave.
            #
            # Both halves are asked, because both are the configuration's fault:
            # whether the package resolves at all, and whether it declares the
            # file type with the 'extension:' an analysis needs. Neither becomes
            # true or false depending on what is installed here.
            options_project, format_name = shape._analysis_implementation(
                ctx, self.analysis, declared=config.implementation
            )
            shape.analysis_getopts(
                ctx,
                self.analysis,
                format_name,
                ctx.get_project(shape.project_name),
                None,
                options_project,
                None,
            )
        except Exception as e:
            return self.failed(shape, "the '%s' implementation could not be resolved: %s", self.analysis, e)

        try:
            result = await shape.analyze_async(ctx, self.analysis)
        except pc_cae.CaeConfigError as e:
            return self.failed(shape, "%s", e)
        except pc_runtime.SandboxUnavailable as e:
            # The one skip. Not "the implementation could not do it" but "the
            # thing that runs implementations is not here": the plugin declared
            # a container and this machine has no container runtime, so nothing
            # was ever asked and nothing can report on the part. Skipping is
            # right precisely because it says nothing about the implementation
            # or the part -- unlike every other way of not producing an answer,
            # which is the implementation failing and fails the check.
            #
            # Uncacheable for the same reason the failures are: starting Docker
            # changes no cache key.
            test_ctx[self.NOT_CACHEABLE] = True
            pc_logging.warning(
                "%s:%s: %s was not run: %s" % (shape.project_name, shape.name, self.analysis.upper(), e)
            )
            return self.TEST_PASSED
        except Exception as e:
            # The implementation was asked and did not deliver. That is a
            # failure whatever the reason -- no solver, no mesher, a sandbox
            # that cannot be built, a crash -- because the part asked a question
            # and got no answer.
            #
            # Reported as `analyze_async` wrote it, which is also what `pc cae`
            # prints: which implementation was asked, what it said, and which
            # machine it did not work on. `pc test` used to compose that here,
            # and then a user who ran the command instead was told less about
            # the same failure. Anything that arrives without a report already
            # on it -- something raised outside the part `analyze_async` wraps
            # -- gets one here, because the two things a bare sentence is
            # missing are exactly the two this check knows.
            #
            # Not remembered, though. This is the one verdict here that can be
            # about the machine rather than about the part, and the cache key
            # describes only the question: the boundary conditions, the
            # implementation, its options. Installing the solver changes none of
            # them, so a cached failure would outlive the reason for it and go
            # on failing a part that now analyses perfectly well.
            test_ctx[self.NOT_CACHEABLE] = True
            report = (
                str(e)
                if isinstance(e, pc_cae.CaeFailed)
                else pc_cae.dysfunction_report(
                    "%s:%s" % (shape.project_name, shape.name),
                    self.analysis,
                    "%s:%s" % (options_project.name, format_name),
                    e,
                )
            )
            return self.failed(shape, "%s", report)

        findings = result.get("findings") or []
        if findings:
            return self.failed(
                shape,
                "%s",
                pc_cae.findings_report("%s:%s" % (shape.project_name, shape.name), self.analysis, findings),
            )
        return self.passed(shape)
